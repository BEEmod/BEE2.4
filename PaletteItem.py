class PaletteItem:
  def __init__(self, key, text, style="ALL"):
    self.text={style : text}
    self.styles={"ALL"}
    if not style == "ALL":
      self.styles.append(style)
      
    subtypes={}
  def addStyle(self, text, style):
    self.text[style]=text
    if not style in self.styles:
      self.styles.append(style)