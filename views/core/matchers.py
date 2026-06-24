"""Resilient element matchers tolerant of Kindle's classic vs Jetpack Compose UI.

Kindle 8.150+ on Android 16 (API 36) renders parts of the UI (notably the bottom
navigation bar) with Jetpack Compose. In the accessibility tree this changes three
things versus the classic Android-View UI:

  * the element class collapses to ``android.view.View`` (was e.g. LinearLayout)
  * ``resource-id`` is the bare Compose testTag (``home_tab``) with no
    ``com.amazon.kindle:id/`` package prefix
  * stateful flags like ``selected`` move onto the element itself rather than a
    child TextView/ImageView, and the ``"…, Tab selected"`` content-desc disappears

These helpers build XPATH strategies that match BOTH trees, so detection keeps
working on the classic UI (older devices / Kindle builds) while also handling the
Compose UI. They are intentionally additive: callers prepend them to existing
strategy lists rather than replacing the classic strategies.
"""

from appium.webdriver.common.appiumby import AppiumBy

_PKG = "com.amazon.kindle"


def id_clause(logical_id):
    """XPATH predicate matching a resource-id in both Compose (bare testTag) and
    classic (``com.amazon.kindle:id/<id>``) forms.
    """
    return f"@resource-id='{logical_id}' or @resource-id='{_PKG}:id/{logical_id}'"


def by_id(logical_id):
    """Class- and prefix-agnostic presence match for a logical resource-id."""
    return (AppiumBy.XPATH, f"//*[{id_clause(logical_id)}]")


def by_id_selected(logical_id):
    """Match a *selected* element by logical id, tolerant of where ``selected``
    lives: on the element itself (Compose) or on a descendant (classic).
    """
    return (
        AppiumBy.XPATH,
        f"//*[({id_clause(logical_id)}) and (@selected='true' or .//*[@selected='true'])]",
    )


def text_ci(text):
    """Case-insensitive exact text match (handles HOME vs Home label re-casing)."""
    lower = text.lower()
    upper = text.upper()
    return (
        AppiumBy.XPATH,
        f"//*[translate(@text, '{upper}', '{lower}')='{lower}']",
    )
