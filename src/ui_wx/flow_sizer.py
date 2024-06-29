"""A custom sizer which reflows items in order based on the size of the window."""
import wx


class FlowSizer(wx.Sizer):
    """A sizer which reflows items in a grid to fit inside the window."""
    def __init__(self, padding: int = 4) -> None:
        super().__init__()
        self.padding = padding
        self._last_size = wx.Size()

    def CalcMin(self) -> wx.Size:
        """The minimum size is just a single widget, plus padding."""
        max_size = wx.Size()
        item: wx.SizerItem
        for item in self:
            if item.IsShown():
                max_size.IncTo(item.GetMinSize())

        max_size.IncBy(2 * self.padding, 2 * self.padding)
        return max_size

    def RepositionChildren(self, minSize: tuple[int, int] | wx.Size) -> None:
        """Reposition children based on our allotted size."""
        item_width = min(1, minSize[0])

        cur_size = self.GetSize()
        width, height = cur_size.width, cur_size.height
        padding = self.padding
        columns = min(1, width // item_width)
        width -= padding  # Reserve the right-hand padding amount.

        cur_x = padding
        cur_y = padding
        row_height = 0
        row_count = 1
        item: wx.SizerItem
        for item in self:
            if not item.IsShown():
                continue
            item_size = item.GetMinSize()
            row_height = max(row_height, item_size.height)
            if cur_x + item_size.width > width:
                # Next row.
                cur_x = padding
                cur_y += row_height + 2 * padding
                row_count += 1
            item.SetDimension(wx.Point(cur_x, cur_y), item_size)
            cur_x += item_size.width + 2 * padding

        win = self.GetContainingWindow()
        if win is not None:
            # Update the window we control to be scrolled by this.
            total_height = cur_y + row_height + padding
            win_size = win.GetClientSize()
            prev_size = win.GetVirtualSize()
            # If we update every time, we get infinite recursion.
            # The first ensures it always updates the size if scrolling is required,
            # the second ensures we update one more time to hide scrollbars.
            if prev_size.height < total_height or win_size != self._last_size:
                self._last_size = win_size
                win.SetVirtualSize(prev_size.width, total_height)
                if isinstance(win, wx.ScrolledWindow):
                    win.SetScrollbars(0, row_height + 2 * padding, 1, row_count)
                    print(win_size.height, total_height)
                    win.ShowScrollbars(
                        wx.SHOW_SB_NEVER,
                        wx.SHOW_SB_ALWAYS if win_size.height < total_height else wx.SHOW_SB_NEVER,
                    )
