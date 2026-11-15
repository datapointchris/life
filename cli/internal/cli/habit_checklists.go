package cli

import (
	"fmt"
	"io"
	"slices"
	"text/tabwriter"
	"time"

	"github.com/datapointchris/goclikit"
	"github.com/spf13/cobra"

	"github.com/datapointchris/life/cli/internal/api"
)

var checklistItemHints = []string{"List a habit's checklist items: life habits items list <habit-id>"}

func newHabitItemsCommand() *cobra.Command {
	cmd := goclikit.AsNamespace(&cobra.Command{
		Use:   "items",
		Short: "List and change a habit's checklist: what its day asks for, and how many times",
		Long: "A habit with checklist items completes itself. Each item has a daily target,\n" +
			"and the tick that brings every item to its target records the habit done for\n" +
			"that day. `life habits tick <item-id>` records one.",
		Example: "  life habits items list 7                         the checklist of habit 7\n" +
			"  life habits items add 7 --name Squat --target 5  five sets of squats a day",
	})
	goclikit.WithRecoveryHints(cmd, append(slices.Clone(habitHints), checklistItemHints...)...)
	splitReadingFromChanging(cmd)
	cmd.AddCommand(inGroup(groupReading, newHabitItemsListCommand())...)
	cmd.AddCommand(inGroup(groupChanging,
		newHabitItemsAddCommand(),
		newHabitItemsEditCommand(),
		newHabitItemsDeleteCommand(),
	)...)
	return cmd
}

func newHabitItemsListCommand() *cobra.Command {
	var asJSON bool
	cmd := &cobra.Command{
		Use:     "list <habit-id>",
		Short:   "List a habit's checklist items and their daily targets",
		Example: "  life habits items list 7",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			habitID, err := parseIntArg("habit id", args[0])
			if err != nil {
				return err
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			items, err := client.ListChecklistItems(cmd.Context(), habitID)
			if err != nil {
				return handleAPIError(err)
			}
			if asJSON {
				return encodeJSON(cmd.OutOrStdout(), items)
			}
			printChecklistItems(cmd.OutOrStdout(), items)
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Output the items as JSON to stdout")
	return cmd
}

func newHabitItemsAddCommand() *cobra.Command {
	var (
		name   string
		target int
		asJSON bool
	)
	cmd := &cobra.Command{
		Use:     "add <habit-id> --name <name> --target <n>",
		Short:   "Add an item to a habit's checklist",
		Example: "  life habits items add 7 --name Squat --target 5",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			habitID, err := parseIntArg("habit id", args[0])
			if err != nil {
				return err
			}
			if name == "" {
				return goclikit.UsageError(fmt.Errorf("--name is required"))
			}
			if target < 1 {
				return goclikit.UsageError(fmt.Errorf("--target must be at least 1, got %d", target))
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			item, err := client.CreateChecklistItem(cmd.Context(), habitID, api.HabitChecklistItemInput{Name: &name, DailyTarget: &target})
			if err != nil {
				return handleAPIError(err)
			}
			if asJSON {
				return encodeJSON(cmd.OutOrStdout(), item)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Added %q, %d a day, to habit %d (item id %d)\n", item.Name, item.DailyTarget, habitID, item.ID)
			return nil
		},
	}
	cmd.Flags().StringVar(&name, "name", "", "Item name (required)")
	cmd.Flags().IntVar(&target, "target", 0, "Times a day the item is done (required)")
	cmd.Flags().BoolVar(&asJSON, "json", false, "Output the created item as JSON to stdout")
	return cmd
}

func newHabitItemsEditCommand() *cobra.Command {
	var (
		name   string
		target int
		asJSON bool
	)
	cmd := &cobra.Command{
		Use:     "edit <item-id> [--name <name>] [--target <n>]",
		Short:   "Rename a checklist item or change its daily target",
		Example: "  life habits items edit 3 --target 4",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			itemID, err := parseIntArg("item id", args[0])
			if err != nil {
				return err
			}
			in := api.HabitChecklistItemInput{}
			if cmd.Flags().Changed("name") {
				in.Name = &name
			}
			if cmd.Flags().Changed("target") {
				in.DailyTarget = &target
			}
			if in == (api.HabitChecklistItemInput{}) {
				return goclikit.UsageError(fmt.Errorf("nothing to change — pass --name or --target"))
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			item, err := client.UpdateChecklistItem(cmd.Context(), itemID, in)
			if err != nil {
				return handleAPIError(err)
			}
			if asJSON {
				return encodeJSON(cmd.OutOrStdout(), item)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Updated %q, %d a day (item id %d)\n", item.Name, item.DailyTarget, item.ID)
			return nil
		},
	}
	cmd.Flags().StringVar(&name, "name", "", "New item name")
	cmd.Flags().IntVar(&target, "target", 0, "New number of times a day")
	cmd.Flags().BoolVar(&asJSON, "json", false, "Output the updated item as JSON to stdout")
	return cmd
}

func newHabitItemsDeleteCommand() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:     "delete <item-id>",
		Short:   "Remove an item from its habit's checklist; its ticks stay as history",
		Example: "  life habits items delete 3 --yes",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			itemID, err := parseIntArg("item id", args[0])
			if err != nil {
				return err
			}
			if !yes {
				ok, err := confirm(cmd, fmt.Sprintf("Delete checklist item %d?", itemID))
				if err != nil {
					return err
				}
				if !ok {
					_, _ = fmt.Fprintln(cmd.ErrOrStderr(), "Aborted.")
					return nil
				}
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			if err := client.DeleteChecklistItem(cmd.Context(), itemID); err != nil {
				return handleAPIError(err)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Deleted checklist item %d\n", itemID)
			return nil
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "Skip the confirmation prompt")
	return cmd
}

func newHabitsTickCommand() *cobra.Command {
	var (
		date   string
		asJSON bool
	)
	cmd := &cobra.Command{
		Use:   "tick <item-id> [--date YYYY-MM-DD]",
		Short: "Record one time a checklist item was done, such as one set",
		Long: "The tick that brings every item on the habit to its target records the habit\n" +
			"done for the day. `life habits today` lists each item's id.",
		Example: "  life habits tick 3\n  life habits tick 3 --date 2026-11-14",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			itemID, err := parseIntArg("item id", args[0])
			if err != nil {
				return err
			}
			day, err := habitCompleteDate(date, time.Now())
			if err != nil {
				return err
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			checklist, err := client.TickChecklistItem(cmd.Context(), itemID, day, LocalZoneName())
			if err != nil {
				return handleAPIError(err)
			}
			if asJSON {
				return encodeJSON(cmd.OutOrStdout(), checklist)
			}
			printChecklist(cmd.OutOrStdout(), checklist)
			return nil
		},
	}
	goclikit.WithRecoveryHints(cmd, checklistItemHints...)
	cmd.Flags().StringVar(&date, "date", "", "Day it was done (YYYY-MM-DD); defaults to today")
	cmd.Flags().BoolVar(&asJSON, "json", false, "Output the habit's checklist as JSON to stdout")
	return cmd
}

func newHabitsUntickCommand() *cobra.Command {
	var (
		date   string
		asJSON bool
	)
	cmd := &cobra.Command{
		Use:   "untick <item-id> [--date YYYY-MM-DD]",
		Short: "Remove the latest tick of a checklist item on a day",
		Long: "Taking an item back below its target removes the habit's completion that\n" +
			"its ticks recorded.",
		Example: "  life habits untick 3",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			itemID, err := parseIntArg("item id", args[0])
			if err != nil {
				return err
			}
			day, err := habitCompleteDate(date, time.Now())
			if err != nil {
				return err
			}
			client, err := newAPIClient(cmd.Context())
			if err != nil {
				return handleAPIError(err)
			}
			board, err := client.GetHabitsDay(cmd.Context(), day, LocalZoneName())
			if err != nil {
				return handleAPIError(err)
			}
			tickID, found := latestTick(board, itemID)
			if !found {
				return fmt.Errorf("item %d has no tick on %s", itemID, day)
			}
			checklist, err := client.UntickChecklistItem(cmd.Context(), itemID, tickID)
			if err != nil {
				return handleAPIError(err)
			}
			if asJSON {
				return encodeJSON(cmd.OutOrStdout(), checklist)
			}
			printChecklist(cmd.OutOrStdout(), checklist)
			return nil
		},
	}
	goclikit.WithRecoveryHints(cmd, checklistItemHints...)
	cmd.Flags().StringVar(&date, "date", "", "Day of the tick to remove (YYYY-MM-DD); defaults to today")
	cmd.Flags().BoolVar(&asJSON, "json", false, "Output the habit's checklist as JSON to stdout")
	return cmd
}

// latestTick finds the item's newest tick on the board's day.
func latestTick(board api.HabitsDay, itemID int) (int, bool) {
	for _, checklist := range board.Checklists {
		for _, item := range checklist.Items {
			if item.ID == itemID && len(item.Ticks) > 0 {
				return item.Ticks[len(item.Ticks)-1].ID, true
			}
		}
	}
	return 0, false
}

func printChecklistItems(out io.Writer, items []api.HabitChecklistItem) {
	if len(items) == 0 {
		_, _ = fmt.Fprintln(out, "No checklist items. Add one with `life habits items add <habit-id> --name ... --target ...`.")
		return
	}
	tw := tabwriter.NewWriter(out, 0, 4, 2, ' ', 0)
	_, _ = fmt.Fprintln(tw, "ID\tNAME\tDAILY TARGET")
	for _, item := range items {
		_, _ = fmt.Fprintf(tw, "%d\t%s\t%d\n", item.ID, item.Name, item.DailyTarget)
	}
	_ = tw.Flush()
}

// printChecklist renders one habit's checklist: a header with how many items
// reached their target, then each item's ticks against its target.
func printChecklist(out io.Writer, checklist api.HabitChecklist) {
	done := 0
	for _, item := range checklist.Items {
		if item.Done {
			done++
		}
	}
	status := fmt.Sprintf("%d of %d items done", done, len(checklist.Items))
	if checklist.Complete {
		status = "complete"
	}
	_, _ = fmt.Fprintf(out, "%s (habit %d), %s: %s\n", checklist.Name, checklist.HabitID, checklist.Date, status)
	tw := tabwriter.NewWriter(out, 0, 4, 2, ' ', 0)
	_, _ = fmt.Fprintln(tw, "  ITEM\tNAME\tDONE")
	for _, item := range checklist.Items {
		_, _ = fmt.Fprintf(tw, "  %d\t%s\t%d/%d\n", item.ID, item.Name, len(item.Ticks), item.DailyTarget)
	}
	_ = tw.Flush()
}
