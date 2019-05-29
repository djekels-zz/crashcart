#
# Copyright (c) 2015 Nutanix Inc. All rights reserved.
#
# Author: akshay@nutanix.com
#
# GUI widgets.
#

import curses

class CursesControl(object):
  def __init__(self):
    self.focus = False
    self.handler = None

  def set_focus(self,hasFocus):
    self.focus = hasFocus
    self.draw()
    if hasFocus:
      curses.curs_set(0)
      self.handler.grabbing_focus(self)

  def keystroke(self,c):
    return self.handler.NOTHING

class FakeCheckBox():
  def __init__(self, selected):
    self.selected = selected

class FakeText():
  def __init__(self, text):
    self.text = text
  def get_selected_data(self):
    return self.text
  def get_displayed_text(self):
    return self.text

class BaseCheckBox(CursesControl):
  def __init__(self,window,y,x,label,selected,
               deselect_if_checked=None,
               deselect_if_unchecked=None,
               disable_if_unchecked=None,
               hide_if_unchecked=None):
    CursesControl.__init__(self)
    self.window = window
    self.x = x
    self.y = y
    self.label = label
    self.selected = selected
    self.deselect_if_checked = deselect_if_checked
    self.deselect_if_unchecked = deselect_if_unchecked
    self.disable_if_unchecked = disable_if_unchecked
    self.hide_if_unchecked = hide_if_unchecked

  def check(self):
    self.selected = True
    self.draw()

  def uncheck(self):
    self.selected = False
    self.draw()

class Button(CursesControl):
  def __init__(self,window,y,x,text,action):
    CursesControl.__init__(self)
    self.window = window
    self.x = x
    self.y = y
    self.text = text
    self.action = action
    self.draw()

  def draw(self):
    color = curses.A_UNDERLINE
    if self.focus:
      color = curses.color_pair(3)
    self.window.addstr(self.y,self.x,self.text,color)

  def keystroke(self,c):
    if c == ord(' ') or c == 10:
      return self.action(self)
    return self.handler.NOTHING

class TextEditor(CursesControl):
  def __init__(self,window,y,x,label,text,width,upper=False):
    CursesControl.__init__(self)
    self.window = window
    self.y = y
    self.x = x
    self.label = label
    self.text = text
    self.width = width
    self.upper = upper
    self.cursor = len(self.text)

  def get_displayed_text(self):
    return self.text

  def draw(self):
    color = 0
    cursor_color = 0
    if self.focus:
      color = curses.color_pair(3)
      cursor_color = curses.color_pair(2) | curses.A_REVERSE

    if not self.visible:
      self.window.addstr(self.y, self.x, " " * (self.width+len(self.label)+1))
      return

    text = self.get_displayed_text()
    text += " " * (self.width-len(text))+" "

    self.window.addstr(self.y,self.x,self.label,0)
    x = self.x+len(self.label)+1

    self.window.addstr(self.y,x,text[:self.cursor],color)
    x += self.cursor
    self.window.addstr(self.y,x,text[self.cursor:self.cursor+1],cursor_color)
    x += 1
    self.window.addstr(self.y,x,text[self.cursor+1:],color)

  def keystroke(self,c):
    if c == curses.KEY_LEFT:
      if self.cursor > 0:
        self.cursor -= 1
        self.draw()
      return self.handler.HANDLED
    elif c == curses.KEY_RIGHT:
      if self.cursor < len(self.text):
        self.cursor += 1
        self.draw()
      return self.handler.HANDLED
    elif c == curses.KEY_BACKSPACE:
      if self.cursor > 0:
        self.cursor -= 1
        self.text = self.text[:self.cursor]+self.text[self.cursor+1:]
        self.draw()
      return self.handler.HANDLED
    elif c == curses.KEY_DC:
      if self.cursor < len(self.text):
        self.text = self.text[:self.cursor]+self.text[self.cursor+1:]
        self.draw()
      return self.handler.HANDLED
    else:
      if c >= 32 and c < 128:
        if len(self.text) < self.width:
          char = chr(c).upper() if self.upper else chr(c)
          self.text = self.text[:self.cursor]+char+self.text[self.cursor:]
          self.cursor += 1
          self.draw()
        return self.handler.HANDLED

class BaseElementHandler(object):
  """
  Handles list of elements, focus and distributes keyboard events
  """
  NOTHING = 0
  EXIT = 1
  NEXT = 2
  HANDLED = 3

  def __init__(self,window):
    self.window = window
    self.elements = []

  def add(self,element,accepts_focus=True,visible=True):
    element.handler = self
    element.accepts_focus = accepts_focus
    element.visible = visible
    self.elements.append(element)
    if visible:
      element.draw()

  def clear(self):
    self.elements = []

  def grabbing_focus(self,element):
    for e in self.elements:
      if e != element:
        e.set_focus(False)

  def get_focused_element_index(self):
    for i in range(len(self.elements)):
      if self.elements[i].focus:
        return i
    raise StandardError("internal error: no element has focus")

  def process(self):
    y = 0
    while 1:
      self.window.refresh()
      c = self.window.getch()
      # self.window.addstr(y,0,str(c)+"   ")
      y = (y+1) % 10
      current_index = self.get_focused_element_index()
      current_ele = self.elements[current_index]
      action = current_ele.keystroke(c)
      if action == self.EXIT:
        self.lastControl = current_ele
        return
      elif action == self.NEXT:
        while not self.elements[newIndex].accepts_focus:
          newIndex = (newIndex+1) % len(self.elements)
        newIndex = (current_index+1) % len(self.elements)
        while not self.elements[newIndex].accepts_focus:
          newIndex = (newIndex+1) % len(self.elements)
        self.elements[newIndex].set_focus(True)
      elif action == self.HANDLED:
        pass
      else:
        if c == 9 or c == 10 or c == curses.KEY_DOWN or c == curses.KEY_RIGHT:
          newIndex = (current_index+1) % len(self.elements)
          while not self.elements[newIndex].accepts_focus:
            newIndex = (newIndex+1) % len(self.elements)
          self.elements[newIndex].set_focus(True)
        elif c == curses.KEY_UP or c == curses.KEY_LEFT:
          newIndex = (current_index-1) % len(self.elements)
          while not self.elements[newIndex].accepts_focus:
            newIndex = (newIndex-1) % len(self.elements)
          self.elements[newIndex].set_focus(True)

class BaseTextViewBlock(CursesControl):
  """
  TextViewBlock reads a file and displays the contents in a scroll-able block.
  """
  def __init__(self, window, y, x, filename, text, label, width, height):
    import textwrap
    CursesControl.__init__(self)
    self.window = window
    self.y = y
    self.x = x
    self.label = ' ' + label + ' '
    self.scrolled_to_end = False
    if width < len(self.label) + 2:
      raise StandardError('TextViewBlock width must be at least 2 characters '
                          'wider than the label.')
    if width < 4:
      raise StandardError('TextViewBlock width must be >= 4.')
    self.width = width
    self.usable_width = width - 2
    if height < 3:
      raise StandardError('TextViewBlock height must be >= 3.')
    self.height = height
    self.usable_height = height - 2
    self.ycursor = 0
    self.blanks = ' ' * self.usable_width
    if not filename:
      self.text = text
      return
    with open(filename, "r") as content:
      text = content.read()
      paras = text.split('\n\n')
      first = True
      self.text = []
      for p in paras:
        if first:
          first = False
        else:
          self.text.append('')
        self.text.extend(textwrap.wrap(p, self.usable_width))
    # note return above @ "if not filename" block
    # add any new, unrelated logic above that

  def sanitize_ycursor(self):
    if self.ycursor + self.usable_height > len(self.text):
      self.scrolled_to_end = True
      self.ycursor = len(self.text) - self.usable_height
    if self.ycursor < 0:
      self.ycursor = 0
