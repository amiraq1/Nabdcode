"""Dynamic skill discovery for NABD OS.

Scans this package for subclasses of BaseSkill and returns them as
ready-to-register instances. A single broken module never stops discovery
of the healthy ones.
"""

import importlib
import logging
import pkgutil

from .base_skill import BaseSkill

logger = logging.getLogger(__name__)


def _discover_skill_classes():
    """Yield (module_name, skill_class) for every concrete BaseSkill subclass."""
    package = __name__
    package_path = __path__

    for module_info in pkgutil.iter_modules(package_path):
        module_name = module_info.name
        if module_name in ("__init__", "base_skill"):
            continue

        full_name = f"{package}.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:  # noqa: BLE001 - per-module isolation
            logger.warning("Skipping module %s: import failed (%s)", full_name, exc)
            continue

        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseSkill)
                and attr is not BaseSkill
                and getattr(attr, "__abstractmethods__", frozenset()) == frozenset()
            ):
                yield module_name, attr


def load_skills():
    """Dynamically discover and instantiate all skills in this package.

    Returns:
        list[BaseSkill]: Instantiated, register-ready skill objects.
    """
    skills = []
    logger.info("Scanning '%s' for skills...", __name__)

    for module_name, skill_cls in _discover_skill_classes():
        try:
            instance = skill_cls()
        except Exception as exc:  # noqa: BLE001 - per-skill isolation
            logger.warning(
                "Skipping skill %s from %s: instantiation failed (%s)",
                getattr(skill_cls, "name", skill_cls.__name__),
                module_name,
                exc,
            )
            continue

        skills.append(instance)
        logger.info(
            "Loaded skill '%s' from %s", instance.name, module_name
        )

    logger.info("Discovery complete: %d skill(s) loaded", len(skills))
    return skills
