"""Sensors for Forsyning Online."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ForsyningOnlineConfigEntry
from .const import DOMAIN
from .coordinator import ForsyningOnlineCoordinator, UsageData


@dataclass(frozen=True, kw_only=True)
class ForsyningOnlineSensorDescription(SensorEntityDescription):
    """Sensor description with a value getter."""

    value_fn: Callable[[UsageData], float | None]


SENSORS: tuple[ForsyningOnlineSensorDescription, ...] = (
    ForsyningOnlineSensorDescription(
        key="today",
        translation_key="today",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        # Resets at midnight; HA treats the drop as a new cycle.
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value_fn=lambda d: d.today,
    ),
    ForsyningOnlineSensorDescription(
        key="yesterday",
        translation_key="yesterday",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda d: d.yesterday,
    ),
    ForsyningOnlineSensorDescription(
        key="last_hour",
        translation_key="last_hour",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda d: d.last_hour,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ForsyningOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ForsyningOnlineSensor(coordinator, entry, description)
        for description in SENSORS
    )


class ForsyningOnlineSensor(CoordinatorEntity[ForsyningOnlineCoordinator], SensorEntity):
    """A usage sensor."""

    entity_description: ForsyningOnlineSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ForsyningOnlineCoordinator,
        entry: ForsyningOnlineConfigEntry,
        description: ForsyningOnlineSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Forsyning Online",
            manufacturer="Forsyning Online",
        )

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        start: datetime | None = self.coordinator.data.last_hour_start
        if self.entity_description.key == "last_hour" and start is not None:
            return {"hour_start": start.isoformat()}
        return None
