package cli

import (
	"strings"
	"unicode/utf8"
)

// listWidth is the number of columns a list table fits in, the width of a
// standard terminal. A row wider than the terminal wraps, and every row after
// it is padded to the widest one, so one long title would wrap them all.
const listWidth = 80

// columnGap is the padding the list tables' tabwriter puts after each column.
const columnGap = 2

// minFreeTextWidth keeps a free-text column readable when the columns before
// it are unusually wide, at the cost of that row running past listWidth.
const minFreeTextWidth = 12

// leadingWidth is how many columns a table's cells take before its free-text
// columns: each column's widest cell, header included, plus the gap after it.
func leadingWidth(header []string, rows [][]string) int {
	total := 0
	for col, title := range header {
		widest := utf8.RuneCountInString(title)
		for _, row := range rows {
			widest = max(widest, utf8.RuneCountInString(row[col]))
		}
		total += widest + columnGap
	}
	return total
}

// truncateTitle fits a title into a column of width runes, collapsing it onto
// one line first: scraped article titles carry the source page's newlines and
// tabs, which would otherwise break the tabwriter's alignment and defeat the
// width limit. A cut title ends in "…".
func truncateTitle(title string, width int) string {
	title = strings.Join(strings.Fields(title), " ")
	runes := []rune(title)
	if len(runes) <= width {
		return title
	}
	return string(runes[:width-1]) + "…"
}
