"""Handles generation for items which are placed as a chain between instances.

This includes Unstationary Scaffolds and Vactubes.
"""
from __future__ import annotations
from typing import Optional, Iterator, TypeVar, Generic, Iterable

from srctools import Entity, Matrix, Vec
import attrs

from precomp import connections
from precomp.connections import Item

__all__ = ['Node', 'chain']
ConfT = TypeVar('ConfT')


@attrs.define(eq=False)
class Node(Generic[ConfT]):
    """Represents a single node in the chain."""
    item: Item = attrs.field(init=True)
    conf: ConfT = attrs.field(init=True)

    # Origin and angles of the instance.
    pos = attrs.field(init=False, default=attrs.Factory(
        lambda self: Vec.from_str(self.item.inst['origin']), takes_self=True,
    ))
    orient = attrs.field(init=False, default=attrs.Factory(
        lambda self: Matrix.from_angstr(self.item.inst['angles']),
        takes_self=True,
    ))

    # The links between nodes
    prev: Optional[Node[ConfT]] = attrs.field(default=None, init=False)
    next: Optional[Node[ConfT]] = attrs.field(default=None, init=False)

    @property
    def inst(self) -> Entity:
        """Return the relevant instance."""
        return self.item.inst

    @classmethod
    def from_inst(cls, inst: Entity, conf: ConfT) -> Node[ConfT]:
        """Find the item for this instance, and return the node."""
        name = inst['targetname']
        try:
            return Node(connections.ITEMS[name], conf)
        except KeyError:
            raise ValueError('No item for "{}"?'.format(name)) from None


def chain(
    node_list: Iterable[Node[ConfT]],
    allow_loop: bool,
) -> Iterator[list[Node[ConfT]]]:
    """Evaluate the chain of items.

    inst_files maps an instance to the configuration to store.
    Lists of nodes are yielded, for each separate track.
    """
    # Name -> node
    nodes: dict[str, Node[ConfT]] = {
        node.item.name: node
        for node in node_list
    }

    # Now compute the links, and check for double-links.
    for node in nodes.values():
        for conn in list(node.item.outputs):
            try:
                next_node = nodes[conn.to_item.name]
            except KeyError:
                # Not one of our instances - fine, it's just actual IO.
                continue
            conn.remove()
            if node.next is not None:
                raise ValueError('Item "{}" links to multiple output items!')
            if next_node.prev is not None:
                raise ValueError('Item "{}" links to multiple input items!')
            node.next = next_node
            next_node.prev = node

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
