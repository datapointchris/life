package cli

import (
	"errors"
	"testing"

	"github.com/datapointchris/goclikit"
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
