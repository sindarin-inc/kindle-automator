"""
Utility functions for extracting and saving book cover images from Kindle screenshots.

This module provides functions to:
1. Extract book cover images from screenshots
2. Save book covers to a user-specific directory
3. Generate URLs for stored book covers
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from PIL import Image
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from server.logging_config import store_page_source

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """
    Convert text to a URL-friendly slug.

    Args:
        text: The text to slugify

    Returns:
        A slugified version of the text (lowercase, spaces to hyphens, remove special chars)
    """
    # Convert to lowercase
    slug = text.lower()

    # Replace spaces with hyphens
    slug = slug.replace(" ", "-")

    # Remove special characters
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Remove duplicate hyphens
    slug = re.sub(r"-+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    return slug


def ensure_covers_directory(sindarin_email: str) -> str:
    """
    Ensure the covers directory exists for the given email.

    Args:
        sindarin_email: The email of the user

    Returns:
        The path to the covers directory
    """
    # Get the project root directory
    project_root = Path(__file__).resolve().parent.parent.parent

    # Create the covers directory if it doesn't exist
    covers_dir = project_root / "covers"

    # Create directory with both Path.mkdir and os.makedirs for robustness
    try:
        covers_dir.mkdir(exist_ok=True)
    except Exception as mkdir_err:
        logger.error(f"Error creating main covers directory with Path.mkdir: {mkdir_err}")
        # Try os.makedirs as a fallback
        try:
            os.makedirs(str(covers_dir), exist_ok=True)
            logger.info(f"Created main covers directory using os.makedirs: {covers_dir}")
        except Exception as makedirs_err:
            logger.error(f"Error creating main covers directory with os.makedirs: {makedirs_err}")
            # Critical error, return empty string to indicate failure
            return ""

    # Create the user-specific covers directory if it doesn't exist
    email_slug = slugify(sindarin_email)
    user_covers_dir = covers_dir / email_slug

    # Create user directory with both methods for robustness
    try:
        user_covers_dir.mkdir(exist_ok=True)
    except Exception as user_mkdir_err:
        logger.error(f"Error creating user covers directory with Path.mkdir: {user_mkdir_err}")
        # Try os.makedirs as a fallback
        try:
            os.makedirs(str(user_covers_dir), exist_ok=True)
            logger.info(f"Created user covers directory using os.makedirs: {user_covers_dir}")
        except Exception as user_makedirs_err:
            logger.error(f"Error creating user covers directory with os.makedirs: {user_makedirs_err}")
            # Critical error, return empty string to indicate failure
            return ""

    # Verify the directories were actually created
    if not os.path.exists(str(covers_dir)):
        logger.error(f"Failed to create main covers directory: {covers_dir}")
        return ""

    if not os.path.exists(str(user_covers_dir)):
        logger.error(f"Failed to create user covers directory: {user_covers_dir}")
        return ""

    # Check if user directory is writable
    if not os.access(str(user_covers_dir), os.W_OK):
        logger.error(f"User covers directory is not writable: {user_covers_dir}")
        try:
            os.chmod(str(user_covers_dir), 0o755)
            logger.info(f"Fixed permissions on user covers directory: {user_covers_dir}")
        except Exception as chmod_err:
            logger.error(f"Failed to fix permissions: {chmod_err}")
            return ""

    return str(user_covers_dir)


def extract_book_cover(driver, book_element, screenshot_path: str, max_retries: int = 3) -> Optional[Dict]:
    """
    Extract the book cover from a screenshot based on the book element's location.

    Args:
        driver: The Appium WebDriver
        book_element: The WebElement representing the book
        screenshot_path: Path to the screenshot image
        max_retries: Maximum number of retries for stale element exceptions

    Returns:
        Dictionary with cover image information or None if extraction failed
    """
    retries = 0

    while retries <= max_retries:
        try:
            # If book_element is None, we can't extract a cover
            if book_element is None:
                logger.error("Cannot extract cover: book_element is None")
                return None

            # Try to find the cover image element
            try:
                # Check if book_element is already the image element
                try:
                    element_resource_id = str(book_element.get_attribute("resource-id"))
                except StaleElementReferenceException:
                    if retries < max_retries:
                        logger.warning(
                            f"Stale element during attribute check (attempt {retries+1}/{max_retries+1}), retrying..."
                        )
                        retries += 1
                        time.sleep(0.5)
                        continue
                    else:
                        logger.error(
                            f"Element is stale during attribute check after {max_retries+1} attempts"
                        )
                        return None

                if "lib_book_row_image" in element_resource_id or "cover_image" in element_resource_id:
                    cover_element = book_element
                else:
                    # Try both possible IDs for cover images
                    try:
                        # First try the new ID
                        try:
                            cover_element = book_element.find_element(
                                AppiumBy.ID, "com.amazon.kindle:id/cover_image"
                            )
                        except StaleElementReferenceException:
                            if retries < max_retries:
                                logger.warning(
                                    f"Stale element during find_element (attempt {retries+1}/{max_retries+1}), retrying..."
                                )
                                retries += 1
                                time.sleep(0.5)
                                continue
                            else:
                                logger.error(
                                    f"Element is stale during find_element after {max_retries+1} attempts"
                                )
                                return None

                        logger.info("Found cover image with ID 'cover_image'")
                    except NoSuchElementException:
                        # Fall back to the old ID
                        logger.info("Trying alternative ID 'lib_book_row_image'")
                        try:
                            cover_element = book_element.find_element(
                                AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_image"
                            )
                        except StaleElementReferenceException:
                            if retries < max_retries:
                                logger.warning(
                                    f"Stale element during fallback find_element (attempt {retries+1}/{max_retries+1}), retrying..."
                                )
                                retries += 1
                                time.sleep(0.5)
                                continue
                            else:
                                logger.error(
                                    f"Element is stale during fallback find_element after {max_retries+1} attempts"
                                )
                                return None

                        logger.info("Found cover image with ID 'lib_book_row_image'")

            except NoSuchElementException:
                logger.error("Could not find cover image element")
                return None

            # Get the location and size of the cover element
            try:
                # Get the location and size using rect (more reliable than separate location/size)
                rect = cover_element.rect
            except StaleElementReferenceException:
                if retries < max_retries:
                    logger.warning(
                        f"Stale element when getting rect (attempt {retries+1}/{max_retries+1}), retrying..."
                    )
                    retries += 1
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"Element is stale when getting rect after {max_retries+1} attempts")
                    return None

            # Extract the coordinates
            left = rect["x"]
            top = rect["y"]
            width = rect["width"]
            height = rect["height"]
            right = left + width
            bottom = top + height

            # Minimum dimensions for a valid cover - reduce minimum size to capture more covers
            min_width, min_height = 60, 80  # Smaller minimum dimensions to catch more potential covers

            # Check if dimensions are too small or odd ratio
            if width < min_width or height < min_height:
                logger.warning(f"Cover dimensions possibly too small: {width}x{height} - saving for review")
                # Continue processing rather than rejecting immediately
                # We'll let downstream validation determine if it's usable

            # Check aspect ratio - but be more lenient as some covers may be different
            # Most Kindle covers have a ratio of about 1:1.5 or 2:3, but we'll accept more variations
            aspect_ratio = height / width
            if aspect_ratio < 0.9:  # If definitely horizontal, log warning but still accept
                logger.warning(f"Unusual aspect ratio: {aspect_ratio:0.2f} - width={width}, height={height}")
                # Don't outright reject, but log the warning

            # Verify the screenshot exists
            if not os.path.exists(screenshot_path):
                logger.error(f"Screenshot does not exist at path: {screenshot_path}")
                return None

            # Log screenshot details
            screenshot_size = os.path.getsize(screenshot_path)

            # Open the screenshot with Pillow
            with Image.open(screenshot_path) as img:
                # Log the screenshot dimensions
                img_width, img_height = img.size

                # Make sure the coordinates are within the image bounds
                left = max(0, left)
                top = max(0, top)
                right = min(img_width, right)
                bottom = min(img_height, bottom)

                # Check that we have valid dimensions after adjustments
                if right <= left or bottom <= top:
                    logger.error(f"Invalid crop dimensions: ({left}, {top}, {right}, {bottom})")
                    return None

                # Crop the image to the cover coordinates
                try:
                    cover_img = img.crop((left, top, right, bottom))

                    # Verify cropped image has reasonable dimensions
                    if cover_img.width < min_width or cover_img.height < min_height:
                        logger.warning(
                            f"Cropped cover image small: {cover_img.width}x{cover_img.height} - continuing anyway"
                        )
                        # Continue processing despite small size

                    # Check for reasonable aspect ratio
                    aspect_ratio = cover_img.height / cover_img.width
                    if aspect_ratio < 1.0:
                        logger.warning(
                            f"Suspicious aspect ratio: {aspect_ratio:0.2f} - width={cover_img.width}, height={cover_img.height}"
                        )
                        # Continue processing despite unusual aspect ratio

                    return {
                        "image": cover_img,
                        "width": cover_img.width,
                        "height": cover_img.height,
                        "coordinates": (left, top, right, bottom),
                    }
                except Exception as crop_err:
                    logger.error(f"Error cropping image: {crop_err}")
                    return None

            # If we reached this point, the current retry attempt failed
            retries += 1
            continue

        except Exception as e:
            logger.error(f"Error extracting book cover: {e}")
            if isinstance(e, StaleElementReferenceException) and retries < max_retries:
                logger.warning(f"Stale element exception (attempt {retries+1}/{max_retries+1}), retrying...")
                retries += 1
                time.sleep(0.5)
                continue
            return None

    # If we've exhausted all retries and still failed
    logger.error(f"Failed to extract book cover after {max_retries+1} attempts")
    return None


def save_book_cover(cover_img, title: str, sindarin_email: str) -> Tuple[bool, str]:
    """
    Save a book cover image to the user's covers directory.

    Args:
        cover_img: The PIL Image of the cover
        title: The title of the book
        sindarin_email: The email of the user

    Returns:
        Tuple of (success: bool, image_path: str)
    """
    try:
        if not title:
            logger.error("Cannot save cover with empty title")
            return False, ""

        if not cover_img:
            logger.error("Cannot save None or empty cover image")
            return False, ""

        # Get the user's covers directory
        covers_dir = ensure_covers_directory(sindarin_email)

        # Verify the directory exists and is writable
        if not os.path.exists(covers_dir):
            logger.error(f"Covers directory does not exist: {covers_dir}")
            # Try to create it again to be sure
            try:
                os.makedirs(covers_dir, exist_ok=True)
                logger.info(f"Created covers directory: {covers_dir}")
            except Exception as dir_err:
                logger.error(f"Failed to create covers directory: {dir_err}")
                return False, ""

        # Check if directory is writable
        if not os.access(covers_dir, os.W_OK):
            logger.error(f"Covers directory is not writable: {covers_dir}")
            return False, ""

        # Create a filename from the slugified title
        slug = slugify(title)
        if not slug:
            # Use a fallback with the first letter of the title or a timestamp
            slug = title[0] if title and title[0].isalnum() else "cover"
            slug += f"_{int(time.time())}"

        filename = f"{slug}.png"
        image_path = os.path.join(covers_dir, filename)

        # Resize the image if it's too large
        max_size = (300, 450)  # Maximum dimensions for cover images

        if cover_img.width > max_size[0] or cover_img.height > max_size[1]:
            logger.info(f"Resizing cover from {cover_img.width}x{cover_img.height} to fit within {max_size}")
            cover_img.thumbnail(max_size, Image.LANCZOS)
            logger.info(f"Resized cover dimensions: {cover_img.width}x{cover_img.height}")

        # Save the image
        try:
            cover_img.save(image_path, format="PNG")
        except Exception as save_err:
            logger.error(f"Error saving image with PIL: {save_err}")

            # Try an alternative approach
            try:
                logger.info("Trying alternative save method")
                cover_img_rgb = cover_img.convert("RGB")
                cover_img_rgb.save(image_path, format="PNG")
                logger.info("Alternative save method successful")
            except Exception as alt_save_err:
                logger.error(f"Alternative save method also failed: {alt_save_err}")
                return False, ""

        # Verify the file was created
        if os.path.exists(image_path):
            file_size = os.path.getsize(image_path)

            # Check if the file size is reasonable
            if file_size < 100:
                logger.warning(f"Cover file is suspiciously small ({file_size} bytes), might be corrupted")

            return True, filename
        else:
            logger.error(f"Failed to save cover, file doesn't exist: {image_path}")

            return False, ""

    except Exception as e:
        logger.error(f"Error saving book cover: {e}")
        return False, ""


def get_cover_url(filename: str, sindarin_email: str) -> str:
    """
    Get the URL for a book cover image.

    Args:
        filename: The filename of the cover image
        sindarin_email: The email of the user

    Returns:
        The URL for the cover image
    """
    # Create a URL path that will be handled by the image serving endpoint
    email_slug = slugify(sindarin_email)
    return f"/covers/{email_slug}/{filename}"


def extract_book_covers_from_screen(
    driver, books, sindarin_email: str, screenshot_path: str, max_retries: int = 3
) -> dict:
    """
    Extract book covers from the current screen and save them to disk.

    Args:
        driver: The Appium WebDriver
        books: List of book dictionaries
        sindarin_email: The email of the user
        screenshot_path: Path to the screenshot image
        max_retries: Maximum number of retries for stale element references

    Returns:
        Dictionary of cover extraction results
    """
    # Ensure the screenshots directory exists
    os.makedirs("screenshots", exist_ok=True)

    # Find book elements
    title_element_map = {}

    try:
        # First, get all title elements and texts
        book_titles_list = driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title")
        title_texts = []

        # Extract the text from each title element to use later
        for title_element in book_titles_list:
            try:
                text = title_element.text
                if text:
                    title_texts.append(text)
            except Exception:
                pass

        # Now get all the cover containers - this gives us the proper parent element
        cover_containers = driver.find_elements(AppiumBy.ID, "com.amazon.kindle:id/cover_container")

        # Process each cover container to find fully visible covers
        for i, container in enumerate(cover_containers):
            try:
                # Check if the container is fully visible
                rect = container.rect

                # Skip if container height is too small (partial visibility at screen edge)
                if rect["height"] < 100:  # Skip tiny containers (partially visible)
                    logger.debug(f"Skipping container {i} due to small height: {rect['height']}")
                    continue

                # Get the image element
                try:
                    image_element = container.find_element(AppiumBy.ID, "com.amazon.kindle:id/cover_image")
                except NoSuchElementException:
                    logger.debug(f"No cover_image found in container {i}")
                    continue

                # Use a different approach - get the button directly by ID
                try:
                    # Find all buttons that have content-desc and contain book info
                    buttons = driver.find_elements(AppiumBy.XPATH, "//android.widget.Button[@content-desc]")

                    # Match by position - look for button with similar position to this container
                    container_y = rect["y"]
                    matching_button = None
                    for button in buttons:
                        try:
                            button_rect = button.rect
                            # If this button is vertically aligned with our container (within 50px)
                            if abs(button_rect["y"] - container_y) < 50:
                                matching_button = button
                                break
                        except:
                            pass

                    # If we found a matching button, use its content-desc
                    if matching_button:
                        content_desc = matching_button.get_attribute("content-desc")
                        # Parse content-desc
                        parts = content_desc.split(",")
                        if parts and parts[0].strip():
                            title = parts[0].strip()
                            # Match with title text elements
                            matching_title = None
                            for known_title in title_texts:
                                if known_title == title or known_title in title or title in known_title:
                                    matching_title = known_title
                                    break

                            if matching_title:
                                title_element_map[matching_title] = image_element
                            else:
                                # Just use the content-desc title
                                title_element_map[title] = image_element
                    else:
                        # Direct lookup approach - find all title elements and pair with this container
                        # Find any title element with a similar vertical position
                        for title_element in driver.find_elements(
                            AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"
                        ):
                            try:
                                title_rect = title_element.rect
                                # If this title element is vertically aligned with our container (within 100px)
                                if abs(title_rect["y"] - container_y) < 100:
                                    title_text = title_element.text
                                    if title_text:
                                        title_element_map[title_text] = image_element
                                        break
                            except:
                                continue
                except Exception as parent_err:
                    logger.debug(f"Error finding matching content-desc for container {i}: {parent_err}")
                    continue
            except Exception as container_err:
                logger.debug(f"Error processing cover container {i}: {container_err}")

        logger.info(f"Found {len(title_element_map)} visible books with titles and cover elements")

        # Extract covers for visible books and return successful extractions
        cover_results = {}  # Store detailed results for debugging

        # Save one more full screenshot right before extraction
        pre_extract_screenshot = f"screenshots/pre_extract_covers_{int(time.time())}.png"
        driver.save_screenshot(pre_extract_screenshot)
        logger.info(f"Saved pre-extraction screenshot to {pre_extract_screenshot}")

        for title, element in title_element_map.items():
            try:
                # Extract cover image with retry capability
                cover_data = extract_book_cover(driver, element, screenshot_path, max_retries)

                if cover_data and "image" in cover_data:
                    # Save the cover image
                    success, filename = save_book_cover(cover_data["image"], title, sindarin_email)

                    # Store detailed result
                    cover_results[title] = {
                        "success": success,
                        "filename": filename if success else None,
                        "coordinates": cover_data.get("coordinates"),
                        "width": cover_data.get("width"),
                        "height": cover_data.get("height"),
                    }

                    if success:
                        logger.info(f"  ✓ '{title}': {cover_data['width']}x{cover_data['height']}")
                    else:
                        logger.warning(f"  ✗ '{title}': No valid cover data")
                else:
                    cover_results[title] = {"success": False, "reason": "No valid cover data"}
                    logger.error(f"Failed to extract cover for '{title}': no valid cover data returned")
            except Exception as e:
                cover_results[title] = {"success": False, "reason": str(e)}
                logger.error(f"Error extracting cover for book '{title}': {e}")

        # Log summary of cover extraction results
        logger.info(
            f"Cover extraction summary: {len(cover_results) - sum(1 for result in cover_results.values() if not result['success'])}/{len(cover_results)} successful"
        )
        for title, result in cover_results.items():
            if result.get("success"):
                logger.info(f"  ✓ '{title}': {result.get('width')}x{result.get('height')}")
            else:
                logger.warning(f"  ✗ '{title}': {result.get('reason')}")

        return cover_results

    except Exception as e:
        logger.error(f"Error finding book elements for cover extraction: {e}")
        return {}


def add_cover_urls_to_books(books, cover_info: dict, sindarin_email: str):
    """
    Add cover_url, cover_width, and cover_height to books that had successful cover extraction.

    Args:
        books: List of book dictionaries to update
        cover_info: Dictionary of cover extraction results (keyed by title)
        sindarin_email: The email of the user

    Returns:
        Updated books list with cover_url, cover_width, and cover_height added
    """
    covers_dir = Path(__file__).resolve().parent.parent.parent / "covers" / slugify(sindarin_email)

    for book in books:
        book_title = book.get("title")
        if book_title and book_title in cover_info:
            info = cover_info[book_title]
            if info.get("success") and info.get("filename"):
                filename = info["filename"]  # Use the filename from cover_info
                cover_path = covers_dir / filename

                if cover_path.exists():
                    book["cover_url"] = get_cover_url(filename, sindarin_email)
                    book["w"] = info.get("width")
                    book["h"] = info.get("height")
                else:
                    logger.warning(
                        f"Cover file for '{book_title}' ('{filename}') doesn't exist at {cover_path} - not adding URL"
                    )
            # No explicit else here, extract_book_covers_from_screen handles logging failures
        # No explicit else here, if book_title not in cover_info, it means no successful cover was processed

    return books
