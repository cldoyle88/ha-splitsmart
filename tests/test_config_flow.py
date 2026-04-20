"""Config flow tests — require pytest-homeassistant-custom-component on Linux.

Run with: pytest -m ha_integration
These are skipped in the default test run (Windows / no phcc).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.splitsmart.const import (
    CONF_CATEGORIES,
    CONF_HOME_CURRENCY,
    CONF_PARTICIPANTS,
    DOMAIN,
)

pytestmark = [pytest.mark.ha_integration, pytest.mark.usefixtures("hass")]


# ------------------------------------------------------------------ helpers


async def _start_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


async def _step(hass: HomeAssistant, flow_id: str, step_id: str, data: dict) -> dict:
    result = await hass.config_entries.flow.async_configure(flow_id, data)
    return result


# ------------------------------------------------------------------ happy path


async def test_full_flow_creates_entry(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    """Happy path: walk every step, confirm the entry has the expected data."""
    flow_id = await _start_flow(hass)

    # user step → participants
    result = await _step(hass, flow_id, "user", {})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "participants"

    # participants step → currency
    result = await _step(
        hass,
        flow_id,
        "participants",
        {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "currency"

    # currency step → categories
    result = await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "categories"

    # categories step → entry created
    result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "Groceries, Utilities"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Splitsmart"
    data = result["data"]
    assert data[CONF_PARTICIPANTS] == [hass_admin_user.id, hass_owner_user.id]
    assert data[CONF_HOME_CURRENCY] == "GBP"
    assert "Groceries" in data[CONF_CATEGORIES]
    assert "Utilities" in data[CONF_CATEGORIES]


# ------------------------------------------------------------------ participants validation


async def test_participants_requires_at_least_two(hass: HomeAssistant, hass_admin_user):
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})

    # Only one participant — should error
    result = await _step(
        hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id]}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "participants"
    assert "min_two_participants" in result.get("errors", {}).get(CONF_PARTICIPANTS, "")


# ------------------------------------------------------------------ categories validation


async def test_categories_requires_at_least_one(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})

    result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "  ,  , "})
    assert result["type"] == FlowResultType.FORM
    assert "min_one_category" in result.get("errors", {}).get(CONF_CATEGORIES, "")


async def test_categories_normalised_to_title_case(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})

    result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "groceries, UTILITIES, eating out"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    cats = result["data"][CONF_CATEGORIES]
    assert "Groceries" in cats
    assert "Utilities" in cats
    assert "Eating Out" in cats


async def test_categories_deduplicates(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})

    result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "Groceries, groceries, GROCERIES"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CATEGORIES].count("Groceries") == 1


# ------------------------------------------------------------------ single-instance guard


async def test_single_instance_only(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    # Create an entry first
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})
    await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "Groceries"})

    # Second flow attempt should abort
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


# ------------------------------------------------------------------ options flow


async def test_options_flow_currency(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    # Set up an entry
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})
    entry_result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "Groceries"})

    entry_id = entry_result["result"].entry_id

    # Start options flow
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "currency"})
    assert result["step_id"] == "currency"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_HOME_CURRENCY: "EUR"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOME_CURRENCY] == "EUR"


async def test_options_flow_categories(hass: HomeAssistant, hass_admin_user, hass_owner_user):
    flow_id = await _start_flow(hass)
    await _step(hass, flow_id, "user", {})
    await _step(hass, flow_id, "participants", {CONF_PARTICIPANTS: [hass_admin_user.id, hass_owner_user.id]})
    await _step(hass, flow_id, "currency", {CONF_HOME_CURRENCY: "GBP"})
    entry_result = await _step(hass, flow_id, "categories", {CONF_CATEGORIES: "Groceries"})

    entry_id = entry_result["result"].entry_id

    result = await hass.config_entries.options.async_init(entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "categories"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_CATEGORIES: "Groceries, Utilities"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "Utilities" in result["data"][CONF_CATEGORIES]
