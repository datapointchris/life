package api

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
)

// HabitChecklistItem is one thing a habit's day asks for, done DailyTarget times.
// A habit with items completes itself when every item reaches its target.
type HabitChecklistItem struct {
	ID          int    `json:"id"`
	HabitID     int    `json:"habit_id"`
	Name        string `json:"name"`
	DailyTarget int    `json:"daily_target"`
}

// HabitItemTick is one time an item was done. TickDate is a YYYY-MM-DD string
// for the same reason as HabitCompleted's CompleteDate.
type HabitItemTick struct {
	ID       int    `json:"id"`
	ItemID   *int   `json:"item_id"`
	HabitID  *int   `json:"habit_id"`
	Name     string `json:"name"`
	TickDate string `json:"tick_date"`
	TickedAt string `json:"ticked_at"`
}

// HabitChecklistItemDay is one item on one day: its ticks, oldest first, and
// whether they reach its target.
type HabitChecklistItemDay struct {
	ID          int             `json:"id"`
	Name        string          `json:"name"`
	DailyTarget int             `json:"daily_target"`
	Ticks       []HabitItemTick `json:"ticks"`
	Done        bool            `json:"done"`
}

// HabitChecklist is a habit's checklist on one day. Complete says every item
// reached its target.
type HabitChecklist struct {
	HabitID  int                     `json:"habit_id"`
	Name     string                  `json:"name"`
	Date     string                  `json:"date"`
	Items    []HabitChecklistItemDay `json:"items"`
	Complete bool                    `json:"complete"`
}

// HabitChecklistItemInput creates an item (both fields) or edits one (only
// those set).
type HabitChecklistItemInput struct {
	Name        *string `json:"name,omitempty"`
	DailyTarget *int    `json:"daily_target,omitempty"`
}

type habitItemTickInput struct {
	TickDate string `json:"tick_date,omitempty"`
}

// ListChecklistItems returns a habit's items (GET /habits/{id}/items).
func (c *Client) ListChecklistItems(ctx context.Context, habitID int) ([]HabitChecklistItem, error) {
	var items []HabitChecklistItem
	if err := c.get(ctx, fmt.Sprintf("/habits/%d/items", habitID), &items); err != nil {
		return nil, err
	}
	return items, nil
}

// CreateChecklistItem adds an item to a habit (POST /habits/{id}/items).
func (c *Client) CreateChecklistItem(ctx context.Context, habitID int, in HabitChecklistItemInput) (HabitChecklistItem, error) {
	var item HabitChecklistItem
	if err := c.send(ctx, http.MethodPost, fmt.Sprintf("/habits/%d/items", habitID), in, &item); err != nil {
		return HabitChecklistItem{}, err
	}
	return item, nil
}

// UpdateChecklistItem applies a partial update (PATCH /habits/items/{id}).
func (c *Client) UpdateChecklistItem(ctx context.Context, itemID int, in HabitChecklistItemInput) (HabitChecklistItem, error) {
	var item HabitChecklistItem
	if err := c.send(ctx, http.MethodPatch, fmt.Sprintf("/habits/items/%d", itemID), in, &item); err != nil {
		return HabitChecklistItem{}, err
	}
	return item, nil
}

// DeleteChecklistItem removes an item (DELETE /habits/items/{id} → 204). Its
// ticks stay as history.
func (c *Client) DeleteChecklistItem(ctx context.Context, itemID int) error {
	return c.send(ctx, http.MethodDelete, fmt.Sprintf("/habits/items/%d", itemID), nil, nil)
}

// TickChecklistItem records one time the item was done (POST
// /habits/items/{id}/ticks) and returns its habit's checklist that day. An empty
// day is today in zone.
func (c *Client) TickChecklistItem(ctx context.Context, itemID int, day string, zone string) (HabitChecklist, error) {
	path := fmt.Sprintf("/habits/items/%d/ticks", itemID)
	if zone != "" {
		path += "?" + url.Values{"timezone": {zone}}.Encode()
	}
	var checklist HabitChecklist
	if err := c.send(ctx, http.MethodPost, path, habitItemTickInput{TickDate: day}, &checklist); err != nil {
		return HabitChecklist{}, err
	}
	return checklist, nil
}

// UntickChecklistItem removes one tick (DELETE /habits/items/{id}/ticks/{tick})
// and returns its habit's checklist on the tick's day.
func (c *Client) UntickChecklistItem(ctx context.Context, itemID, tickID int) (HabitChecklist, error) {
	var checklist HabitChecklist
	if err := c.send(ctx, http.MethodDelete, fmt.Sprintf("/habits/items/%d/ticks/%d", itemID, tickID), nil, &checklist); err != nil {
		return HabitChecklist{}, err
	}
	return checklist, nil
}
