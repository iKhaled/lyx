# This file is part of lyx2lyx

''' 
This file has code for straightforward conversion of LyX format to XML.
'''

from parser_tools import find_end_of
from xml.sax.saxutils import escape
from xml_streamer import XmlStreamer
import re
import sys

debug = False

mixed_tags = { 'emph':'default', 'shape':'default', 'series':'default', 'color':'inherit', 'lang':'english'}

def _fix_text_styling(lines, debugcb):
    stack = []
    fixes = []
    i = 0
    while i < len(lines):
        #debugcb('looking at line %d: %s' % (i, lines[i]))
        line = lines[i]
        if not line.startswith('\\') or line.find(' ') == -1:
            #debugcb('1 i++ at %d' % (i,))
            i += 1
            continue
        line = _chomp(line[1:])
        a = line[0:line.find(' ')]
        if not a in mixed_tags:
            #debugcb('2 i++ at %d' % (i,))
            i += 1
            continue
        v = line[line.find(' ') + 1:]
        if v != mixed_tags[a]:
            # We're opening a new whatever it is.
            # XXX But we need to handle the possibility that we're
            # changing the whatever it is!  How to handle this?  We
            # could convert
            #  \lang french foo \lang spanish bar \lang english foobar
            # to
            #  <lang a="french">foo<lang a="spanish">bar</lang></lang>
            # or to
            #  <lang a="french">foo</lang><lang a="spanish">bar</lang>
            # The latter would be easier: just close all tags up to the
            # farthest one in the stack for the tag being closed, then
            # re-open any others that were found along the way.  But the
            # former is clearly more correct!  And that requires
            # handling in this case right here, which means re-factoring
            # some of the code from the elif: the code to close and
            # re-open tags.
            #debugcb('seen \\%s at line %d' % (line, i))
            stack.append((a, v))
            #debugcb('3 i++ at %d' % (i,))
            i += 1
        elif stack[-1][0] != a:
            # We're closing a whatever it is, but out of order.
            debugcb('fixing ordering for \\%s at line %d, stack = %s' % (a, i, repr(stack)))
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == a:
                    debugcb('fixed ordering for \\%s' % (a,))
                    del(stack[k])
                    continue
                debugcb('fixing ordering for \\%s by closing %s' % (a, stack[k][0]))
                lines.insert(i, '\\' + stack[k][0] + ' ' + mixed_tags[a])
                #debugcb('4 i++ at %d' % (i,))
                i += 1
            #debugcb('5 i++ at %d' % (i,))
            i += 1
            m = 0
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == a:
                    break
                lines.insert(i, '\\' + stack[k][0] + ' ' + stack[k][1])
                debugcb('fixing ordering for \\%s by re-opening %s %s' % (a, stack[k][0], stack[k][1]))
                m += 1
            #debugcb('6 i += %d at %d' % (m, i))
            i += m
        else:
            assert stack[-1][0] == a
            stack.pop()
            #debugcb('7 i++ at %d' % (i,))
            i += 1
    return lines


def _chomp(line):
    " Remove end of line char(s)."
    if line[-1] != '\n':
        return line
    if line[-2:-1] == '\r':
        return line[:-2]
    return line[:-1]

def _cmd_type(tag, rest):
    if tag != 'inset':
        return None
    if rest.startswith('CommandInset') or rest.startswith('Float') or rest.startswith('listings'):
        return 'inset'
    if rest == 'Tabular':
        return 'XML'
    return None

def _parse_begin(line):
    assert line.startswith('\\begin_') or line.startswith('\\index ')
    line = _chomp(line)
    if line.startswith('\\index '):
        return ('index', '\\index', '\end_index', None, line[line.find(' ') + 1:])
    sp = line.find(' ')
    if sp >= 0:
        tag = line[len('\\begin_'):sp]
        start_tok = line[0:sp]
        rest = line[sp + 1:]
    else:
        tag = line[len('\\begin_'):]
        start_tok = line
        rest = None
    return (tag, start_tok, '\end_' + tag, _cmd_type(tag, rest), rest)

def _parse_attr(line):
    line = _chomp(line)
    if line.startswith('\\'):
        line = line[1:]
    if line == '':
        return (None, None)
    sp = line.find(' ')
    if sp == -1:
        return (line, 'true')
    a = line[0:sp]
    if a in mixed_tags:
        return (None, None)
    v = line[sp + 1:]
    if v[0] == '"':
        v = v[1:]
    if v[-1] == '"':
        v = v[0:-1]
    return (a, v)

def _parse_xml_tag(line):
    line = _chomp(line)
    assert line.startswith('<') and not line.startswith('</')
    end = line.rfind('>')
    if line[end - 1] == '/':
        end -= 1
    tag_end = line.find(' ')
    if tag_end < 0:
        tag_end = end
    tag = line[1:tag_end]
    start_tok = line[0:tag_end]
    end_tok = '</' + tag
    attrs = []
    s = line[tag_end + 1:end]
    while len(s) > 0:
        s = s.strip()
        if s.find('=') == -1:
            break
        end = s.index('=')
        attr = s[0:end]
        quote = s[end + 1]
        s = s[end + 2]
        # XXX We should look for an unquoted double quote
        end = s.find(quote)
        val = s[0:end]
        attrs.append((attr, val))
        s = s[end + 1:]
    return (tag, attrs, start_tok, end_tok)

def _lyxml2xml(lines, xout, start, end, debugcb):
    i = start
    while i < end:
        debugcb('Parsing line %d: %s' % (i, lines[i]))
        if lines[i].startswith('</'):
            xout.end_elt(lines[i][2:-2])
            i += 1
        elif lines[i].startswith('<'):
            (tag, attrs, start_tok, end_tok) = _parse_xml_tag(lines[i])
            # There don't seem to be tags with no child nodes in .lyx,
            # but let's handle them just in case.
            if lines[i][-2] != '/':
                e = find_end_of(lines, i, start_tok, end_tok)
                debugcb('find_end_of(%d, %s, %s) = %d' % (i, start_tok, end_tok, e))
                # lyxtabular's <column> and <features> don't get closed!
                # What a mess.
                if e == -1:
                    e = None
            else:
                e = None
            xout.start_elt(tag)
            xout.attr('embedded_xml', 'true')
            for a in attrs:
                xout.attr(a[0], a[1])
            if e:
                i = _lyxml2xml(lines, xout, i + 1, e, debugcb)
                debugcb('_lyx2xml(...) = %d, looking for %d' % (i, e))
                if i + 1 == e:
                    i += 1
                else:
                    debugcb('_lyx2xml() returned %d, e = %d' % (i, e))
            else:
                xout.end_elt(tag)
                i += 1
        else:
            i = _lyx2xml(lines, xout, debugcb, i, end)
    return i

def _handle_interspersed_attrs(lines, xout, start, end, debugcb):
    i = start
    depth = 0
    while i < end:
        if lines[i].startswith('\\begin_') or lines[i].startswith('\\index '):
            depth += 1
        elif lines[i].startswith('\\end_'):
            depth -= 1
        elif depth == 0 and lines[i].startswith('\\'):
            (a, v) = _parse_attr(lines[i])
            if a and v:
                debugcb('lines[%d] = %s' % (i, lines[i]))
                xout.attr(a, v)
                if a == 'language':
                    mixed_tags['lang'] = v
        i += 1

def _key(line):
    if len(line) > 0 and line[0] == '\\' and line.find(' ') > -1:
        if line.find(' ') > -1:
            return line[1:line.find(' ')]
        else:
            return _chomp(line[1:])
    return None

def _lyx2xml(lines, xout, debugcb, start=0, end=-1, cmd_type=None):
    i = start
    if end < 0:
        end = len(lines)
    prev_i = -1
    while i < end:
        debugcb('Parsing line %d: %s' % (i, lines[i]))
        assert i > prev_i
        prev_i = i
        if len(lines[i]) == 0 or lines[i] == ' ':
            # Ignore empty lines
            i += 1
            cmd_type = None
        elif lines[i][0] == '#':
            # LyX source comment
            #xout.comment(lines[i][1:])
            i += 1
            cmd_type = None
        elif lines[i].startswith('\\begin_') or lines[i].startswith('\\index '):
            (el, start_tok, end_tok, cmd_type, rest) = _parse_begin(lines[i])
            xout.start_elt(el)
            if el == 'inset' and not cmd_type and (i + 1) < end and lines[i + 1].startswith('status '):
                i += 1 # skip status open|collapsed line
                status = lines[i][lines[i].find(' ') + 1:]
            else:
                status = None
            debugcb('lines[%d] = %s' % (i, lines[i]))
            if rest:
                xout.attr('thing_name', rest)
            e = find_end_of(lines, i, start_tok, end_tok)
            assert e != -1
            debugcb('find_end_of(%d, %s, %s) = %d' % (i, start_tok, end_tok, e))
            # XXX Here we need to find any attributes that might be
            # interspersed with child nodes so we can suck them in
            # first.  What a PITA.
            _handle_interspersed_attrs(lines, xout, i + 1, e - 1, debugcb)
            if status:
                xout.attr('status', status)
            i = _lyx2xml(lines, xout, debugcb, i + 1, e, cmd_type)
            debugcb('_lyx2xml(...) = %d, looking for %s at %d; end = %d' % (i, end_tok, e, end))
            if i + 1 == e:
                i += 1
            else:
                debugcb('_lyx2xml() returned %d, e = %d; end = %d' % (i, e, end))
            assert lines[i].startswith('\\end_')
            xout.end_elt(el)
            cmd_type = None
            i += 1
        elif cmd_type == 'inset':
            # Parse "\begin_inset CommandInset ..." attributes
            debugcb('lines[%d] = %s' % (i, lines[i]))
            while i < end and lines[i] != '' and lines[i] != ' ':
                (a, v) = _parse_attr(lines[i])
                if not a or not v:
                    break
                xout.attr(a, v)
                i += 1
            # then suck in content
            cmd_type = None
        elif cmd_type == 'XML':
            # Parse embedded XML contents
            i = _lyxml2xml(lines, xout, i, end, debugcb)
            cmd_type = None
        elif lines[i][0] == '\\' and \
           not lines[i].startswith('\\begin_') and \
           not lines[i].startswith('\\end_') and \
           not _key(lines[i]) in mixed_tags:
            # An attribute, which we've handled above with the call to
            # _handle_interspersed_attrs().
            i += 1
        else:
            line = lines[i]
            if xout.stack[-1] == 'layout':
                line = _chomp(line)
            key = _key(line)
            debugcb('FOO: %s from %s' % (key,line))
            if key in mixed_tags:
                val = _chomp(lines[i][lines[i].find(' ') + 1:])
                if val == 'default':
                    xout.end_elt(key)
                else:
                    xout.start_elt(key)
                    xout.attr('type', val)
            else:
                xout.text(escape(line))
            cmd_type = None
            i += 1
    return i

def read_lyx(f):
    f = open(f, 'r')
    lines = f.readlines()
    f.close()
    #for i in range(len(lines)):
    #    lines[i] = _chomp(lines[i])
    return lines

def lyx2xml(lines, outcb, debugcb=None):
    def _debugcb(s):
        if not debugcb:
            return
        debugcb(s)
    xout = XmlStreamer(outcb, 'lyx') # pass in name of DTD
    xout.start_elt('lyx')
    sys.stdout.write('\n\n')
    lines = _fix_text_styling(lines, _debugcb)
    #debugcb('Fixed lines:\n')
    #for i in range(len(lines)):
    #    debugcb('%d %s' % (i + 1, lines[i]))
    _lyx2xml(lines, xout, _debugcb)
    xout.end_elt('lyx')
    xout.finish()
    return True
