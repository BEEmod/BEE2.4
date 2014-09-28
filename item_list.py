class ItemList(dict):
    "Version of dicts that can inherit items from a parent style."
	def __init__(self, base=None):
        self.base=base
	def __missing__(key):
        "Called if list[key] fails, so look at the parent's list next."
        if self.base:
            return self.base[key] # This will recurse until an item is found.
        else:
            return None