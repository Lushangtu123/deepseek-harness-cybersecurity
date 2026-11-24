```json
{
  "verdict": "PASS-for-gap-delivery",
  "reviewScope": "Text-only review of supplied evidence. No tools/MCP/hooks, no execution, and no independent filesystem or archive hash verification.",
  "boundOutcome": {
    "sourceCandidate": "affef050148f527c0a21dfb7c989eded6cd9c07f30f945ba9eb1048395d27f63",
    "completedGroups": 9,
    "nativePassed": 168,
    "nativeTotal": 168,
    "stoppedBefore": "rev6-24",
    "stopReason": "suite-capacity-admission",
    "full20Passed": false,
    "formalTargets": "0/16",
    "r3": "blocked",
    "officialOverallResourceStatus": "unknown-row-coverage",
    "oneSubmissionOnly": true,
    "noReplay": true,
    "releaseOrCleanupApproval": false
  },
  "accuracyAndBinding": {
    "nineGroupResultConsistentAcrossSuppliedEvidence": true,
    "capacityExplanationBound": true,
    "emptyFrameTransportAndArchiveGateConsistent": true,
    "partialLiveObservationsKeptDistinctFromOfficialStatus": true,
    "derivedExtractionExplicitlyDisclosed": true,
    "fullRawReadbackEnclosed": false,
    "independentRawHashClaimMade": false
  },
  "limitations": [
    "The delivery extract is derived and labeled as such; the full raw VM response and full raw 93-file readback are not enclosed in this text-only packet.",
    "Partial live observations of exited controller/groups/roles, absent stage, removed container records, and released batch lock are observations only, not official whole-run resource closure.",
    "Failure-time exact first_usage is not logged; 56,220,214 is post-stop and is not substituted for it.",
    "This is not a PASS for full20 execution, R3 approval, release, auto-cleanup, or whole-run resource closure."
  ],
  "reportingOrEvidenceBlockers": []
}
```
