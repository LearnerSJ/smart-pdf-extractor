"""Document assembler.

Merges per-page extraction outputs into a single AssembledDocument with:
- Page ordering
- XY-cut reading order within each page
- Multi-page table stitching
- Provenance tagging on all elements
"""

from __future__ import annotations

import structlog

from pipeline.models import AssembledDocument, PageOutput, Token

logger = structlog.get_logger()


def assemble(page_outputs: list[PageOutput]) -> AssembledDocument:
    """Assemble per-page outputs into a unified document.

    Applies XY-cut reading order to text blocks within each page,
    stitches multi-page tables, and preserves provenance on all elements.

    Args:
        page_outputs: List of PageOutput objects, one per page, in page order.

    Returns:
        AssembledDocument with merged blocks, tables, token stream, and provenance.
    """
    # Sort by page number to ensure correct ordering
    sorted_pages = sorted(page_outputs, key=lambda p: p.page_number)

    all_blocks: list[dict[str, object]] = []
    all_tables: list[dict[str, object]] = []
    all_tokens: list[Token] = []

    for page_output in sorted_pages:
        # Apply XY-cut reading order to text blocks
        ordered_blocks = _xy_cut_order(page_output.text_blocks, page_output.page_number)
        all_blocks.extend(ordered_blocks)

        # Collect tables
        all_tables.extend(page_output.tables)

        # Collect tokens in page order
        all_tokens.extend(page_output.tokens)

    # Stitch multi-page tables
    stitched_tables = _stitch_multi_page_tables(all_tables)

    provenance: dict[str, object] = {
        "total_pages": len(sorted_pages),
        "page_numbers": [p.page_number for p in sorted_pages],
        "classifications": {
            p.page_number: p.classification for p in sorted_pages
        },
    }

    logger.info(
        "document.assembled",
        total_pages=len(sorted_pages),
        total_blocks=len(all_blocks),
        total_tables=len(stitched_tables),
        total_tokens=len(all_tokens),
    )

    return AssembledDocument(
        blocks=all_blocks,
        tables=stitched_tables,
        token_stream=all_tokens,
        provenance=provenance,
    )


def _xy_cut_order(
    text_blocks: list[dict[str, object]], page_number: int
) -> list[dict[str, object]]:
    """Apply XY-cut algorithm to determine reading order of text blocks.

    The XY-cut algorithm recursively splits the page into horizontal and
    vertical strips based on whitespace gaps, producing a natural reading order.

    For simplicity, this implementation uses a top-to-bottom, left-to-right
    recursive bisection approach:
    1. Find the largest horizontal gap → split into top/bottom groups
    2. Within each group, find the largest vertical gap → split into left/right
    3. Recurse until groups are small enough

    Args:
        text_blocks: List of text block dicts with 'bbox' key [x0, y0, x1, y1].
        page_number: Page number for provenance.

    Returns:
        Text blocks reordered according to XY-cut reading order.
    """
    if len(text_blocks) <= 1:
        return text_blocks

    return _xy_cut_recursive(text_blocks)


def _xy_cut_recursive(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    """Recursively apply XY-cut to a set of blocks.

    Strategy:
    - Try horizontal cut first (split into rows)
    - If no good horizontal cut, try vertical cut (split into columns)
    - If neither works, sort top-to-bottom, left-to-right
    """
    if len(blocks) <= 1:
        return blocks

    # Extract bounding boxes
    bboxes = []
    for block in blocks:
        bbox = block.get("bbox", [0, 0, 0, 0])
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            bboxes.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
        else:
            bboxes.append((0.0, 0.0, 0.0, 0.0))

    # Try horizontal cut (split by Y coordinate)
    h_split = _find_horizontal_split(bboxes)
    if h_split is not None:
        top_blocks = [b for b, bb in zip(blocks, bboxes) if bb[1] < h_split]
        bottom_blocks = [b for b, bb in zip(blocks, bboxes) if bb[1] >= h_split]
        if top_blocks and bottom_blocks:
            return _xy_cut_recursive(top_blocks) + _xy_cut_recursive(bottom_blocks)

    # Try vertical cut (split by X coordinate)
    v_split = _find_vertical_split(bboxes)
    if v_split is not None:
        left_blocks = [b for b, bb in zip(blocks, bboxes) if bb[0] < v_split]
        right_blocks = [b for b, bb in zip(blocks, bboxes) if bb[0] >= v_split]
        if left_blocks and right_blocks:
            return _xy_cut_recursive(left_blocks) + _xy_cut_recursive(right_blocks)

    # Fallback: sort top-to-bottom, then left-to-right
    return sorted(blocks, key=lambda b: (
        float(b.get("bbox", [0, 0, 0, 0])[1]) if isinstance(b.get("bbox"), (list, tuple)) else 0,
        float(b.get("bbox", [0, 0, 0, 0])[0]) if isinstance(b.get("bbox"), (list, tuple)) else 0,
    ))


def _find_horizontal_split(
    bboxes: list[tuple[float, float, float, float]],
) -> float | None:
    """Find the best horizontal split point (largest Y gap between blocks).

    Args:
        bboxes: List of (x0, y0, x1, y1) tuples.

    Returns:
        Y coordinate of the split point, or None if no good split found.
    """
    if len(bboxes) < 2:
        return None

    # Sort by top Y coordinate
    sorted_by_y = sorted(bboxes, key=lambda bb: bb[1])

    # Find largest gap between bottom of one block and top of next
    best_gap = 0.0
    best_split = None

    for i in range(len(sorted_by_y) - 1):
        current_bottom = sorted_by_y[i][3]  # y1 of current
        next_top = sorted_by_y[i + 1][1]  # y0 of next
        gap = next_top - current_bottom

        if gap > best_gap:
            best_gap = gap
            best_split = (current_bottom + next_top) / 2

    # Only split if gap is meaningful (> 5 units)
    if best_gap > 5.0:
        return best_split

    return None


def _find_vertical_split(
    bboxes: list[tuple[float, float, float, float]],
) -> float | None:
    """Find the best vertical split point (largest X gap between blocks).

    Args:
        bboxes: List of (x0, y0, x1, y1) tuples.

    Returns:
        X coordinate of the split point, or None if no good split found.
    """
    if len(bboxes) < 2:
        return None

    # Sort by left X coordinate
    sorted_by_x = sorted(bboxes, key=lambda bb: bb[0])

    # Find largest gap between right of one block and left of next
    best_gap = 0.0
    best_split = None

    for i in range(len(sorted_by_x) - 1):
        current_right = sorted_by_x[i][2]  # x1 of current
        next_left = sorted_by_x[i + 1][0]  # x0 of next
        gap = next_left - current_right

        if gap > best_gap:
            best_gap = gap
            best_split = (current_right + next_left) / 2

    # Only split if gap is meaningful (> 20 units — columns are wider than line gaps)
    if best_gap > 20.0:
        return best_split

    return None


def _stitch_multi_page_tables(
    tables: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Stitch tables that span multiple pages.

    Heuristic: If a table on page N+1 has the same headers as a table on page N,
    and the page N table is the last table on that page, merge them.

    Args:
        tables: All tables from all pages, in page order.

    Returns:
        Tables with multi-page tables merged.
    """
    if len(tables) <= 1:
        return tables

    stitched: list[dict[str, object]] = []
    skip_indices: set[int] = set()

    for i, table in enumerate(tables):
        if i in skip_indices:
            continue

        current = table
        # Look ahead for continuation tables
        for j in range(i + 1, len(tables)):
            if j in skip_indices:
                continue

            next_table = tables[j]
            current_page = current.get("page_number", 0)
            next_page = next_table.get("page_number", 0)

            # Check if next table is on the immediately following page
            if isinstance(current_page, int) and isinstance(next_page, int):
                if next_page != current_page + 1:
                    break

            # Check if headers match
            current_headers = current.get("headers", [])
            next_headers = next_table.get("headers", [])

            if current_headers and next_headers and current_headers == next_headers:
                # Merge rows
                current_rows = current.get("rows", [])
                next_rows = next_table.get("rows", [])
                if isinstance(current_rows, list) and isinstance(next_rows, list):
                    merged_rows = current_rows + next_rows
                    current = {
                        **current,
                        "rows": merged_rows,
                        "page_range": _get_page_range(current, next_table),
                        "provenance": {
                            **(current.get("provenance", {}) if isinstance(current.get("provenance"), dict) else {}),
                            "multi_page": True,
                        },
                    }
                    skip_indices.add(j)
            else:
                break

        stitched.append(current)

    return stitched


def _get_page_range(
    table1: dict[str, object], table2: dict[str, object]
) -> list[int]:
    """Compute the page range for a stitched table."""
    pages: set[int] = set()

    # Get pages from table1
    if "page_range" in table1 and isinstance(table1["page_range"], list):
        pages.update(int(p) for p in table1["page_range"] if isinstance(p, int))
    elif "page_number" in table1 and isinstance(table1["page_number"], int):
        pages.add(table1["page_number"])

    # Get pages from table2
    if "page_range" in table2 and isinstance(table2["page_range"], list):
        pages.update(int(p) for p in table2["page_range"] if isinstance(p, int))
    elif "page_number" in table2 and isinstance(table2["page_number"], int):
        pages.add(table2["page_number"])

    return sorted(pages)
