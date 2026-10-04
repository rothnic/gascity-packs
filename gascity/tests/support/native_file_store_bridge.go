// This executable is test support, not a production gc command.
// Build it inside an isolated copy of the pinned Gas City module so it uses
// that revision's real FileStore, ID allocator, locks, and dependency semantics.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/gastownhall/gascity/internal/beads"
	"github.com/gastownhall/gascity/internal/fsys"
)

type request struct {
	Operation string            `json:"operation"`
	ID        string            `json:"id"`
	Bead      beads.Bead        `json:"bead"`
	Metadata  map[string]string `json:"metadata"`
	Status    *string           `json:"status"`
	Assignee  *string           `json:"assignee"`
	ParentID  *string           `json:"parent"`
	Target    string            `json:"target"`
	DepType   string            `json:"dep_type"`
}

func run() error {
	if len(os.Args) != 2 {
		return fmt.Errorf("usage: native-file-store-bridge ABS_STORE_PATH")
	}
	var req request
	if err := json.NewDecoder(os.Stdin).Decode(&req); err != nil {
		return err
	}
	store, err := beads.OpenFileStore(fsys.OSFS{}, os.Args[1], beads.WithFileStoreIDPrefix(os.Getenv("GC_NATIVE_FILE_PREFIX")))
	if err != nil {
		return err
	}
	var result any
	switch req.Operation {
	case "create":
		result, err = store.Create(req.Bead)
	case "show":
		var b beads.Bead
		b, err = store.Get(req.ID)
		if err == nil {
			b.Dependencies, err = store.DepList(req.ID, "down")
		}
		result = b
	case "update":
		err = store.Update(req.ID, beads.UpdateOpts{
			Metadata: req.Metadata, Status: req.Status,
			Assignee: req.Assignee, ParentID: req.ParentID,
		})
		if err == nil {
			result, err = store.Get(req.ID)
		}
	case "dep-add":
		err = store.DepAdd(req.ID, req.Target, req.DepType)
		result = map[string]bool{"ok": err == nil}
	case "dep-list":
		result, err = store.DepList(req.ID, "down")
	default:
		return fmt.Errorf("unsupported test operation %q", req.Operation)
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "native file store fixture:", err)
		os.Exit(1)
	}
}
