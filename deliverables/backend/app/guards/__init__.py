"""
Guards: intake-time validation and cross-tab contradiction checks (Work Breakdown
package 4.0) -- e.g. conflicting EAU definitions across sheets, SoP dates that
disagree, invalid design-status/stage pairings. Applied identically at the direct-
entry form and at bulk import (see [[opptrack-intake-not-excel]] -- direct entry is
the primary intake path, import is migration/backfill only).
"""
