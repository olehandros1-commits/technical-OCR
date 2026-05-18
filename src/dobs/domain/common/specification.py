from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from functools import reduce
from operator import and_, or_


class Specification[T](ABC):
    __slots__ = ()

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        raise NotImplementedError

    def __and__(self, other: Specification[T]) -> AndSpecification[T]:
        return AndSpecification(left=self, right=other)

    def __or__(self, other: Specification[T]) -> OrSpecification[T]:
        return OrSpecification(self, other)

    def __invert__(self) -> NotSpecification[T]:
        return NotSpecification(self)

    def __call__(self, candidate: T) -> bool:
        return self.is_satisfied_by(candidate)

    @classmethod
    def all_of(cls, specs: Iterable[Specification[T]]) -> Specification[T] | None:
        items = list(specs)
        if not items:
            return None
        return reduce(and_, items)

    @classmethod
    def any_of(cls, specs: Iterable[Specification[T]]) -> Specification[T] | None:
        items = list(specs)
        if not items:
            return None
        return reduce(or_, items)


class AndSpecification[T](Specification[T]):
    __slots__ = ("left", "right")

    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) and self.right.is_satisfied_by(candidate)


class OrSpecification[T](Specification[T]):
    __slots__ = ("left", "right")

    def __init__(self, left: Specification[T], right: Specification[T]) -> None:
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) or self.right.is_satisfied_by(candidate)


class NotSpecification[T](Specification[T]):
    __slots__ = ("spec",)

    def __init__(self, spec: Specification[T]) -> None:
        self.spec = spec

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self.spec.is_satisfied_by(candidate)
