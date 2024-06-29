"""A custom sizer which reflows items in order based on the size of the window."""
import wx


class FlowSizer(wx.Sizer):
    """A sizer which reflows items in a grid to fit inside the window."""
    def __init__(self, padding: int = 4) -> None:
        super().__init__()
        self.padding = padding

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
            item.SetDimension(wx.Point(cur_x, cur_y), item_size)
            cur_x += item_size.width + 2 * padding
