package cli

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	"github.com/datapointchris/goclikit"

	"github.com/datapointchris/life/cli/internal/api"
)

func TestLastReadInstant_SendsEachShapeAsAnInstant(t *testing.T) {
	cases := map[string]string{
		"2026-07-24":           "2026-07-24T12:00:00-04:00",
		"2026-07-24T09:00:00":  "2026-07-24T09:00:00-04:00",
		"2026-07-24T09:00:00Z": "2026-07-24T09:00:00Z",
	}
	for value, want := range cases {
		got, err := lastReadInstant(value, newYork(t))
		if err != nil {
			t.Errorf("%s: unexpected error: %v", value, err)
			continue
		}
		if got != want {
			t.Errorf("%s: sent %s, want %s", value, got, want)
		}
	}
}

func TestLastReadInstant_AnythingElseIsAUsageError(t *testing.T) {
	_, err := lastReadInstant("last tuesday", newYork(t))
	if !errors.Is(err, errLastReadFormat) {
		t.Fatalf("want errLastReadFormat, got %v", err)
	}
	if !errors.Is(err, goclikit.ErrUsage) {
		t.Errorf("want a usage error, so the exit is 2 rather than 1, got %T", err)
	}
}

// A batch that is not paused has no ResumesAt. Printing it reaches the nil
// guard, and without the guard the dereference panics and fails this test.
func TestPrintBulkImportStatus_ABatchWithNoResumeTimePrints(t *testing.T) {
	status := api.ArticleBulkImportStatus{BatchID: "batch", Status: "processing", Total: 3, Processed: 1}

	var out bytes.Buffer
	printBulkImportStatus(&out, status)

	if !strings.Contains(out.String(), "batch") {
		t.Errorf("the batch id is missing:\n%s", out.String())
	}
}
