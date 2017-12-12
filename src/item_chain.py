"""Handles generation for items which are placed as a chain between instances.

This includes Unstationary Scaffolds and Vactubes.
"""
from typing import Any, Dict, Container, List, Optional, Iterator

import connections
from srctools import Entity, VMF
from connections import Item


class Node:
    """Represents a single node in the chain."""
    def __init__(self, item: Item):
        self.item = item
        self.conf = None  # type: Any
        self.prev = None  # type: Optional[Node]
        self.next = None  # type: Optional[Node]

    @property
    def inst(self) -> Entity:
        return self.item.inst


def chain(
    vmf: VMF,
    inst_files: Container[str],
    allow_loop: bool,
) -> Iterator[List[Node]]:
    """Evaluate the chain of items.

    inst is the instances that are part of this chain.
    Lists of nodes are yielded, for each seperate track.
    """
    # Name -> node
    nodes = {}  # type: Dict[str, Node]

    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in inst_files:
            continue
        name = inst['targetname']
        try:
            nodes[name] = Node(connections.ITEMS[name])
        except KeyError:
            raise ValueError('No item for "{}"?'.format(name)) from None

    # Now compute the links, and check for double-links.
    for name, node in nodes.items():
        has_other_io = False
        for conn in list(node.item.outputs):
            try:
                next_node = nodes[conn.to_item.name]
            except KeyError:
                # Not one of our instances - fine, it's just actual
                # IO.
                has_other_io = True
                continue
            conn.remove()
            if node.next is not None:
                raise ValueError('Item "{}" links to multiple output items!')
            if next_node.prev is not None:
                raise ValueError('Item "{}" links to multiple input items!')
            node.next = next_node
            next_node.prev = node

        # If we don't have real IO, we can delete the antlines automatically.
        if not has_other_io:
            for ent in node.item.antlines:
                ent.remove()
            for ent in node.item.ind_panels:
                ent.remove()
            node.item.antlines.clear()
            node.item.ind_panels.clear()

    todo = set(nodes.values())
    while todo:
        # Grab a random node, then go backwards until we find the start.
        # If we return back to this node, it's an infinite loop.
        pop_node = todo.pop()

        if pop_node.prev is None:
            start_node = pop_node
        else:
            start_node = pop_node.prev
            while True:
                if start_node.prev is None:
                    break
                # We've looped back.
                elif start_node is pop_node:
                    if not allow_loop:
                        raise ValueError('Loop in linked items!')
                    break
                start_node = start_node.prev

        node_list = []
        node = start_node
        while True:
            node_list.append(node)
            todo.discard(node)
            if node.next is None:
                break
            node = node.next
            if node is start_node:
                break

        yield node_list
