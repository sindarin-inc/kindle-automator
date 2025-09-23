# Page Number OCR Implementation

## Summary of What Was Built

### 1. **Screenshot Region Cropping** (`server/utils/ocr_utils.py`)
- Added `extract_page_indicator_regions()` - Extracts bottom-left (page indicator) and bottom-right (percentage) regions
- Added `process_screenshot_with_regions()` - Processes a single screenshot to extract:
  - Main text (top 85% of screen)
  - Page indicator text (bottom-left corner)
  - Percentage text (bottom-right corner)
- Benefits: Single screenshot is shared for all OCR operations, improving efficiency

### 2. **Page Format Pattern System** (`handlers/reader_handler.py`)
- Created `PAGE_FORMAT_PATTERNS` dictionary with regex patterns for:
  - `page_of`: "Page X of Y"
  - `location_of`: "Location X of Y"
  - `time_left`: "X minutes/hours left"
  - `learning_speed`: "Learning reading speed"
  - `percentage_only`: "X%"
- Enhanced `_parse_position_text()` to:
  - Accept separate percentage text
  - Return location info alongside page info
  - Log unknown formats to `logs/unknown_page_formats.log`
  - Support extensible pattern matching

### 3. **OCR-Based Progress Extraction** (`handlers/reader_handler.py`)
- Added `get_reading_progress_from_ocr()`:
  - Takes optional screenshot bytes (reuses existing screenshots)
  - OCRs page indicator and percentage regions separately
  - Returns standard progress format matching existing `get_reading_progress()`
- Added `rotate_page_format_with_ocr()`:
  - Rotates through page formats by tapping bottom-left
  - Tracks seen formats to detect cycles
  - Stops when finding "Page X of Y" format

### 4. **Text Resource Updates** (`server/resources/text_resource.py`)
- Modified to use single screenshot for both text and page info
- Added `debug_ocr=1` parameter for testing
- Default behavior: Use OCR for page numbers (no dialog)
- `position=1` or `position_dialog=1`: Use traditional dialog method
- Returns existing `progress` format for backwards compatibility

### 5. **Tap Coordinates Fix**
- Updated tap location to (10% width, 97% height) to avoid triggering page flip dialog
- Page flip was triggering at 85-95% height range

## Current Issues

1. **OCR Quality**: The page indicator area is returning garbage text like "# 1.1.1.1.1..."
   - This might be because the page indicator is not visible by default
   - Or the cropping regions need adjustment for the specific screen size

2. **Page Flip Dialog**: Original tap coordinates (92% height) were triggering the page flip view
   - Fixed by moving tap to 97% height, but needs testing

3. **Database Connection**: Server restart failed due to PostgreSQL not running
   - Need to start Docker containers: `cd ../web-app && make fast`

## Next Steps to Complete Implementation

### 1. Fix OCR Region Detection
```python
# Adjust crop regions based on actual page indicator location
# Current: bottom 15% of screen
# May need to be more precise or check if indicator is visible first
```

### 2. Add Page Indicator Visibility Check
```python
def is_page_indicator_visible(driver):
    """Check if page indicator is actually displayed"""
    from views.reading.view_strategies import PAGE_NUMBER_IDENTIFIERS
    for strategy, locator in PAGE_NUMBER_IDENTIFIERS:
        try:
            element = driver.find_element(strategy, locator)
            if element and element.is_displayed():
                return True
        except:
            continue
    return False
```

### 3. Test Format Rotation
- Verify tap coordinates don't trigger page flip
- Confirm format cycles through: Location → Page → Time → etc.
- Ensure OCR correctly identifies each format

### 4. Integration Testing
```bash
# Test debug mode to see raw OCR results
curl "http://localhost:4096/kindle/text?user_email=kindle@solreader.com&debug_ocr=1"

# Test normal mode (should rotate to page format automatically)
curl "http://localhost:4096/kindle/text?user_email=kindle@solreader.com"

# Test with position dialog (old behavior)
curl "http://localhost:4096/kindle/text?user_email=kindle@solreader.com&position_dialog=1"
```

### 5. Navigation Integration
- Update `/navigate` endpoint to use OCR by default
- Only use dialog when `position=1` is explicitly set
- Ensure session tracking works with OCR-extracted page numbers

## Benefits of This Approach

1. **No Center Tap**: Avoids placemark/footnote dialog issues
2. **Efficient**: Single screenshot for both text and page info
3. **Extensible**: Easy to add new page format patterns
4. **Backwards Compatible**: Existing `position=1` behavior preserved
5. **Debug Mode**: Can inspect raw OCR results for troubleshooting

## Files Modified

- `server/utils/ocr_utils.py` - Added region extraction and multi-region OCR
- `handlers/reader_handler.py` - Added OCR progress methods and pattern matching
- `server/resources/text_resource.py` - Integrated shared screenshot approach
- `views/reading/view_strategies.py` - (Referenced for identifiers)

## Testing Commands

```bash
# Start server
make claude-run

# Test OCR extraction
make test-api  # Run integration tests

# Manual testing
curl -H "Authorization: Tolkien $WEB_INTEGRATION_TEST_AUTH_TOKEN" \
     -H "Cookie: staff_token=$INTEGRATION_TEST_STAFF_AUTH_TOKEN" \
     "http://localhost:4096/kindle/text?user_email=kindle@solreader.com&debug_ocr=1"
```

## Known Patterns to Support

- "Page X of Y" - Standard page format (desired)
- "Location X of Y" - Kindle location format
- "X minutes left in chapter" - Time-based progress
- "X hours Y minutes left in book" - Book time remaining
- "Learning reading speed" - Initial reading state
- "X%" - Percentage only (usually on right side)

## Debug Logging

- Page indicator OCR results logged at INFO level
- Unknown formats logged to `logs/unknown_page_formats.log`
- Debug mode returns raw OCR text for all regions