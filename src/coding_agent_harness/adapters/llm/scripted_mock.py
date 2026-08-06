from __future__ import annotations


class ScriptedMockLLM:
    def __init__(self, actions) -> None:
        self._actions = tuple(actions)
        self._index = 0
        self._contexts = []

    @property
    def contexts(self):
        return tuple(self._contexts)

    def generate(self, context):
        self._contexts.append(context)
        if self._index >= len(self._actions):
            raise RuntimeError("script exhausted")
        action = self._actions[self._index]
        self._index += 1
        return action
