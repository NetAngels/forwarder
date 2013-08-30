# -*- coding: utf-8 -*-
class cached_property(object):
    """
    Декоратор, превращающий метод в кэшируемое свойство.
    Скопировано из django.utils.functional.
    """
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, type):
        res = instance.__dict__[self.func.__name__] = self.func(instance)
        return res


class DictDiff(object):
    """
    Считает разницу между двумя словарями, возвращая ее в виде сетов ключей.
    """
    def __init__(self, old, new):
        self.old, self.new = old, new
        self.set_old, self.set_new = set(new.iterkeys()), set(old.iterkeys())
        self.intersect = self.set_old & self.set_new

    @cached_property
    def added(self):
        return self.set_old - self.intersect

    @cached_property
    def removed(self):
        return self.set_new - self.intersect

    @cached_property
    def changed(self):
        return set(o for o in self.intersect if self.new[o] != self.old[o])

    @cached_property
    def unchanged(self):
        return set(o for o in self.intersect if self.new[o] == self.old[o])


