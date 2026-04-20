"""Config flow and options flow for Splitsmart."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    COMMON_CURRENCIES,
    CONF_CATEGORIES,
    CONF_HOME_CURRENCY,
    CONF_NAMED_SPLITS,
    CONF_PARTICIPANTS,
    DEFAULT_CATEGORIES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# ISO-4217 codes available in the currency picker (common first, then alphabetical)
_ALL_CURRENCIES = [
    *COMMON_CURRENCIES,
    *(
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "FJD",
        "FKP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HRK",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "STN",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "UYU",
        "UZS",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWL",
    ),
]
# Deduplicate while preserving order
_seen: set[str] = set()
CURRENCY_OPTIONS: list[str] = []
for _c in _ALL_CURRENCIES:
    if _c not in _seen:
        CURRENCY_OPTIONS.append(_c)
        _seen.add(_c)


def _parse_categories(raw: str) -> list[str]:
    """Split a comma/newline-delimited string, title-case, deduplicate."""
    parts = [p.strip().title() for p in raw.replace("\n", ",").split(",")]
    seen: set[str] = set()
    result: list[str] = []
    for p in parts:
        if p and p not in seen:
            result.append(p)
            seen.add(p)
    return result


async def _get_ha_user_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Return HA users as selector options, excluding system accounts."""
    users = await hass.auth.async_get_users()
    options = []
    for user in users:
        if user.system_generated or not user.is_active:
            continue
        options.append(selector.SelectOptionDict(value=user.id, label=user.name or user.id))
    return options


class SplitsmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Welcome step — just a Continue button."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return await self.async_step_participants()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_participants(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick HA users who share the ledger."""
        errors: dict[str, str] = {}
        user_options = await _get_ha_user_options(self.hass)

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_PARTICIPANTS, [])
            if len(selected) < 2:
                errors[CONF_PARTICIPANTS] = "min_two_participants"
            else:
                self._data[CONF_PARTICIPANTS] = selected
                return await self.async_step_currency()

        return self.async_show_form(
            step_id="participants",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PARTICIPANTS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_currency(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick the home currency."""
        if user_input is not None:
            self._data[CONF_HOME_CURRENCY] = user_input[CONF_HOME_CURRENCY]
            return await self.async_step_categories()

        return self.async_show_form(
            step_id="currency",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOME_CURRENCY, default="GBP"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=CURRENCY_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit the category list."""
        errors: dict[str, str] = {}
        default_text = ", ".join(DEFAULT_CATEGORIES)

        if user_input is not None:
            cats = _parse_categories(user_input.get(CONF_CATEGORIES, ""))
            if not cats:
                errors[CONF_CATEGORIES] = "min_one_category"
            else:
                self._data[CONF_CATEGORIES] = cats
                self._data[CONF_NAMED_SPLITS] = {}
                return self.async_create_entry(title="Splitsmart", data=self._data)

        return self.async_show_form(
            step_id="categories",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CATEGORIES, default=default_text): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                            type=selector.TextSelectorType.TEXT,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Re-enter at the participants step; requires integration reload."""
        errors: dict[str, str] = {}
        user_options = await _get_ha_user_options(self.hass)

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_PARTICIPANTS, [])
            if len(selected) < 2:
                errors[CONF_PARTICIPANTS] = "min_two_participants"
            else:
                entry = self._get_reconfigure_entry()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PARTICIPANTS: selected},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PARTICIPANTS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SplitsmartOptionsFlow(config_entry)


class SplitsmartOptionsFlow(OptionsFlow):
    """Options flow — currency, categories, named splits."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["currency", "categories"],
        )

    async def async_step_currency(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Change home currency."""
        current = self._entry.options.get(
            CONF_HOME_CURRENCY, self._entry.data.get(CONF_HOME_CURRENCY, "GBP")
        )
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self._entry.options, CONF_HOME_CURRENCY: user_input[CONF_HOME_CURRENCY]},
            )

        return self.async_show_form(
            step_id="currency",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOME_CURRENCY, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=CURRENCY_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Edit category list."""
        current_cats = self._entry.options.get(
            CONF_CATEGORIES, self._entry.data.get(CONF_CATEGORIES, DEFAULT_CATEGORIES)
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            cats = _parse_categories(user_input.get(CONF_CATEGORIES, ""))
            if not cats:
                errors[CONF_CATEGORIES] = "min_one_category"
            else:
                return self.async_create_entry(
                    title="",
                    data={**self._entry.options, CONF_CATEGORIES: cats},
                )

        return self.async_show_form(
            step_id="categories",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CATEGORIES, default=", ".join(current_cats)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                            type=selector.TextSelectorType.TEXT,
                        )
                    )
                }
            ),
            errors=errors,
        )
