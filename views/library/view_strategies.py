from appium.webdriver.common.appiumby import AppiumBy

# Invalid Item dialog detection
INVALID_ITEM_DIALOG_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@text='Invalid Item' and @resource-id='com.amazon.kindle:id/alertTitle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/alertTitle' and @text='Invalid Item']",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Please remove the item from your device')]"),
]

# View identification strategies
LIBRARY_VIEW_IDENTIFIERS = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_root_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_recycler_container']"),
    # Secondary identifiers - specific to library functionality
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_top_tool_bar_layout']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sort_filter']"),  # View options button
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/filter_root']"),  # Filter section
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/search_box']"),  # Search box
    # View-specific identifiers
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
    # Navigation identifiers - updated for tablet layout
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
]

# Empty library with sign-in button identifiers
EMPTY_LIBRARY_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sign in to access your Kindle Library')]"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_empty_view']"),
    (
        AppiumBy.ID,
        "com.amazon.kindle:id/empty_library_logged_out",
    ),  # Container for empty library when logged out
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),  # Sign-in button in empty library
]

# Text indicators for empty library requiring sign-in
EMPTY_LIBRARY_TEXT_INDICATORS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'empty here')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sign in to access your Kindle Library')]"),
]

LIBRARY_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'LIBRARY, Tab')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
]

LIBRARY_TAB_SELECTION_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
]

# Bottom navigation bar identifiers
BOTTOM_NAV_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_bar']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_bar_inflated']",
    ),
]

# View mode identifiers
GRID_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/grid_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/grid_recycler_view']"),
    (AppiumBy.XPATH, "//android.widget.GridView[@resource-id='com.amazon.kindle:id/recycler_view']"),
]

LIST_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/lib_book_row_title']"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']//android.widget.RelativeLayout[@resource-id='com.amazon.kindle:id/lib_book_row_title_container']",
    ),
]

# Book metadata identifiers
BOOK_METADATA_IDENTIFIERS = {
    "title": [
        # Primary title identifier - start with the recycler view and find titles within it
        (
            AppiumBy.XPATH,
            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']",
        ),
        # Alternative title identifiers
        (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"),
    ],
    "progress": [
        (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_reading_progress"),
        (
            AppiumBy.XPATH,
            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_reading_progress']",
        ),
    ],
    "size": [
        (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_file_size"),
        (
            AppiumBy.XPATH,
            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_file_size']",
        ),
    ],
    "author": [
        # Direct ID lookup
        (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_author"),
        # Standard XPath lookup
        (
            AppiumBy.XPATH,
            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_author']",
        ),
        # Relative XPath within title container
        (
            AppiumBy.XPATH,
            ".//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_author']",
        ),
        # Find author as sibling of title in the same parent container
        (
            AppiumBy.XPATH,
            "//android.widget.RelativeLayout[@resource-id='com.amazon.kindle:id/lib_book_row_title_container']/android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_author']",
        ),
        # Find any author element in the current view
        (
            AppiumBy.XPATH,
            "//*[@resource-id='com.amazon.kindle:id/lib_book_row_author']",
        ),
    ],
    "container": [
        # Primary container strategy - find the book buttons directly
        (
            AppiumBy.XPATH,
            "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']/android.widget.Button",
        ),
        # Fallback to title elements if buttons not found
        (
            AppiumBy.XPATH,
            "//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']",
        ),
        # Alternative container strategy - find title containers
        (
            AppiumBy.XPATH,
            "//android.widget.RelativeLayout[@resource-id='com.amazon.kindle:id/lib_book_row_title_container']",
        ),
    ],
}

# Additional container relationship strategies
BOOK_CONTAINER_RELATIONSHIPS = {
    # Strategy to find title container within a book button
    "title_container": (
        AppiumBy.XPATH,
        ".//android.widget.RelativeLayout[@resource-id='com.amazon.kindle:id/lib_book_row_title_container']",
    ),
    # Strategy to find parent RelativeLayout containing a specific title
    "parent_by_title": (
        AppiumBy.XPATH,
        ".//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text={title}]]",
    ),
    # Strategy to find any ancestor RelativeLayout containing a specific title
    "ancestor_by_title": (
        AppiumBy.XPATH,
        "//android.widget.RelativeLayout[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title' and @text={title}]]",
    ),
}

# Search box and search interface identifiers
SEARCH_BOX_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/search_box"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/search_box']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/search_box_text_view']"),
]

SEARCH_INPUT_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/search_query"),
    (AppiumBy.ID, "com.amazon.kindle:id/search_src_text"),
    (AppiumBy.ID, "com.amazon.kindle:id/search_edit_text"),
    (AppiumBy.ID, "android:id/search_src_text"),
    (AppiumBy.ID, "com.amazon.kindle:id/search_text_field"),
    (
        AppiumBy.XPATH,
        "//android.widget.EditText[contains(@content-desc, 'search') or contains(@text, 'search') or contains(@hint, 'search') or contains(@resource-id, 'search')]",
    ),
]

SEARCH_BACK_BUTTON_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@content-desc='Navigate up' or @content-desc='Back' or @content-desc='back']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Navigate up']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Back']"),
]

SEARCH_RESULTS_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/grid_search_result"),
    (AppiumBy.ID, "com.amazon.kindle:id/search_recycler_view"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/search_recycler_view']",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'In your library')]"),
]

SEARCH_RESULT_ITEM_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/badgeable_cover"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/search_recycler_view']//*[@clickable='true']",
    ),
]

# Content description parsing strategies
CONTENT_DESC_STRATEGIES = {
    # Non-author terms to filter out when parsing content-desc
    "non_author_terms": ["book", "volume", "downloaded", "series", "with foreword", "foreword", "with", "by"],
    # Patterns for content-desc formats
    "patterns": [
        # Pattern: "Title, Author, ..."
        {"split_by": ", ", "author_index": 1, "name": "Simple title-author comma separated"},
        # Pattern: "Title, Author, Book not downloaded., ..."
        {
            "split_by": ", ",
            "author_index": 1,
            "skip_if_contains": ["Book not downloaded"],
            "name": "Title-author with not downloaded status",
        },
        # Pattern: "Series: Title, N volumes, , Author;Author2"
        {
            "split_by": ", ",
            "author_index": -1,
            "process": lambda s: s.split(";")[0] if ";" in s else s,
            "name": "Series with multiple authors",
        },
        # Pattern: "Title, with foreword by X, Author, ..."
        {"split_by": ", ", "author_index": 2, "name": "Title with foreword, then author"},
        # Pattern: "Title, with foreword by X, Author, ..."
        {"split_by": ", ", "author_index": 3, "name": "Title with longer foreword, then author"},
        # Additional patterns that might help with the null author issue:
        {"split_by": " by ", "author_index": 1, "name": "Title by Author format"},
        {"split_by": "Author: ", "author_index": 1, "name": "Explicit Author: prefix"},
        {"split_by": ": ", "author_index": 1, "name": "Title: Subtitle or Author format"},
    ],
    # Author name cleanup rules
    "cleanup_rules": [
        # Remove "with foreword by" and similar phrases
        {"pattern": r"with foreword by.*", "replace": ""},
        # Remove anything after semicolon (co-authors)
        {"pattern": r";.*", "replace": ""},
        # Remove non-author indicators
        {"pattern": r"Book \d+", "replace": ""},
        {"pattern": r"\(.*\)", "replace": ""},
        # Additional cleanup rules that might help with the null author issue:
        {"pattern": r"^by\s+", "replace": ""},  # Remove leading "by "
        {"pattern": r"^Author:\s+", "replace": ""},  # Remove leading "Author: "
        {"pattern": r"READ$", "replace": ""},  # Remove trailing READ tag
        {"pattern": r"\s+READ\s+", "replace": " "},  # Remove READ surrounded by spaces
    ],
}

BOOK_AUTHOR_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/lib_book_row_author']"),
]

# Library tab selection strategies - moved from view_inspector.py
LIBRARY_TAB_SELECTION_STRATEGIES = [
    # Primary strategy - check for exact content-desc match
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    # Secondary strategy - check for selected child elements
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
    # Additional strategy - check for both child elements being selected
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab'][.//android.widget.ImageView[@selected='true'] and .//android.widget.TextView[@selected='true']]",
    ),
    # Fallback strategy - check for content-desc without selected attribute
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected' and .//android.widget.ImageView[@selected='true'] and .//android.widget.TextView[@selected='true']]",
    ),
]

# Library tab child element selection strategies - moved from library_handler.py
LIBRARY_TAB_CHILD_SELECTION_STRATEGIES = [
    # Check for selected icon and label together
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
]

# Library-specific element detection strategies
LIBRARY_ELEMENT_DETECTION_STRATEGIES = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_recycler_container']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_root_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_screenlet_root']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_view_root']"),
]

# Combined library view detection strategies
LIBRARY_VIEW_DETECTION_STRATEGIES = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_root_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_recycler_container']"),
    # Secondary identifiers - specific to library functionality
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_top_tool_bar_layout']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sort_filter']"),  # View options button
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/filter_root']"),  # Filter section
    # Search box removed as it overlaps with search results view
]

# View options menu strategies
VIEW_OPTIONS_MENU_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"),  # DONE button
]

# View options done button strategies
VIEW_OPTIONS_DONE_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"),  # DONE button
]

# Library content container strategies
LIBRARY_CONTENT_CONTAINER_STRATEGIES = [
    # Removed reader_content_container as it's actually a reader view element
    # and was causing confusion between LIBRARY and READING views
]

# Reader drawer layout identifiers
READER_DRAWER_LAYOUT_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_drawer_layout"),
]

# WebView identifiers
WEBVIEW_IDENTIFIERS = [
    (AppiumBy.CLASS_NAME, "android.webkit.WebView"),
]

# Reader content identifiers
READER_CONTENT_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_container"),
]

# Reader footer identifiers
READER_FOOTER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_container"),
]
