
# Copyright (c) 2018 Nutanix Inc. All rights reserved.
#
# Author: sadhana.kannan@nutanix.com
#
# GUI widgets for network crashcart
#
import curses

import gui_widgets

NOTHING = 0
EXIT = 1
NEXT = 2
HANDLED = 3
CANCEL = 4

class CheckBox(gui_widgets.BaseCheckBox):
  def __init__(self, window, y, x, label, selected, accepts_input=True,
               disable_if_unchecked=None, hide_if_unchecked=None,
               update_if_unchecked=None):
    super(CheckBox, self).__init__(window, y, x, label, selected,
                                   None, None, disable_if_unchecked,
                                   hide_if_unchecked)

    self.accepts_input = accepts_input
    self.update_if_unchecked = update_if_unchecked
    self.draw()

  def draw(self):
    color = 0
    if self.focus:
      color = curses.color_pair(3)

    if not self.accepts_input:
      self.window.addstr(self.y, self.x, "[-]", color)
      set_entity_visible(False, self.disable_if_unchecked)

    elif self.selected:
      self.window.addstr(self.y, self.x, "[x]", color)
      set_entity_visible(self.selected, self.disable_if_unchecked)

    else:
      self.window.addstr(self.y, self.x, "[ ]", color)
      set_entity_visible(False, self.disable_if_unchecked)

    self.window.addstr(self.y, self.x+4, self.label, 0)

  def keystroke(self, c):
    if not self.accepts_input:
      return self.handler.NOTHING
    if c == ord(' '):
      self.selected = not self.selected
      self.draw()
      set_entity_visible(self.selected, self.disable_if_unchecked)
      update_button_text(self.selected, self.update_if_unchecked)
    return self.handler.NOTHING

class CrashCartButton(gui_widgets.Button):
  def __init__(self, window, y, x, text, action):
    super(CrashCartButton, self).__init__(window, y, x, text, action)

  def update_text(self, text):
    self.text = text
    self.draw()

class TextViewBlock(gui_widgets.BaseTextViewBlock):
  """
  TextViewBlock reads a file and displays the contents in a scroll-able block.
  """
  def __init__(self, window, y, x, filename, text, label, width, height):
    super(TextViewBlock, self).__init__(window, y, x, filename, text,
                                        label, width, height)
    self.org_label = self.label

  def draw(self):
    y = self.y
    end_line = min(self.ycursor + self.usable_height -1, len(self.text)- 1)
    end_line = str(end_line)

    self.label = (self.org_label +
                  " (showing %s of %s)" % (end_line, len(self.text) - 1))
    banner = '*' * ((self.width - len(self.label)) / 2)
    if len(self.label) % 2 == 1 and self.width % 2 == 0:
      b2 = '*'
    else:
      b2 = ''
    self.window.addstr(y, self.x, banner + self.label + banner + b2, self.width)
    y += 1
    for line in range(self.ycursor, self.ycursor + self.usable_height):
      txt = ''
      if len(self.text) > line:
        txt = self.text[line]
      l = len(txt)
      self.window.addstr(y, self.x, '|' + txt +
                         self.blanks[0:self.usable_width - l] + '|',self.width)
      y += 1
    self.window.addstr(y, self.x, '*' * self.width,self.width)

  def keystroke(self,c):
    if c == curses.KEY_UP:
      self.ycursor -= 1
    elif c == curses.KEY_DOWN:
      self.ycursor += 1
    elif c == curses.KEY_PPAGE:
      self.ycursor -= self.usable_height - 1
    elif c == curses.KEY_NPAGE:
      self.ycursor += self.usable_height - 1
    else:
      return self.handler.NOTHING
    self.sanitize_ycursor()
    self.draw()

    if c == curses.KEY_UP:
      if self.ycursor == 0:
        return self.handler.NOTHING
    if c == curses.KEY_DOWN:
      if self.scrolled_to_end:
        return self.handler.NOTHING

    return self.handler.HANDLED

class ElementHandler(gui_widgets.BaseElementHandler):
  """
  Handles list of elements, focus and distributes keyboard events.
  """
  def __init__(self, window):
    super(ElementHandler, self).__init__(window)

  def process(self):
    while 1:
      self.window.refresh()
      c = self.window.getch()
      current_index = self.get_focused_element_index()
      current_ele = self.elements[current_index]
      action = current_ele.keystroke(c)
      if action == self.EXIT:
        if (type(current_ele) == CrashCartButton and
            current_ele.text == "Cancel"):
          return CANCEL
        else:
          self.lastControl = current_ele
          return self.EXIT
      elif action == self.NEXT:
        if type(current_ele) == CrashCartButton and current_ele.text == "Next":
            self.window.clear()
            return self.NEXT
        if type(current_ele) == CrashCartButton and current_ele.text == "Done":
            return self.EXIT
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
            newIndex = (newIndex) % len(self.elements)
          self.elements[newIndex].set_focus(True)
    return self.NOTHING

def set_entity_visible(selected, entities):
  if not entities:
    return True
  for entity in entities:
    entity.accepts_input = selected
    entity.draw()

def update_button_text(selected, entities):
  if not entities:
    return True
  for entity in entities:
    text = "Done"
    if selected:
      text = "Next"
    entity.update_text(text)

def generate_row_text(entries, sizes):
  row_entries = []
  for entry, size in zip(entries, sizes):
    row_entries.append(entry.ljust(size))
  return ":".join(row_entries)
