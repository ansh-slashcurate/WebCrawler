import { useState } from "react";
import TenderLaunchForm from "./tenders/TenderLaunchForm";
import TenderTagsPanel from "./tenders/TenderTagsPanel";
import TenderResultsView from "./tenders/TenderResultsView";

// Deliberately self-contained: its own launch form, its own tag management,
// its own results view - separate from the Dashboard's NewCrawlForm/entity-crawl
// flow and from Runs/RunDetail. Saved bank sites live on the Settings page
// instead (App.jsx lifts `prefillSeed` so "Use as seed" there can jump here
// with the seed URL/bank name already filled in). The only thing this page
// shares with the rest of the app is the underlying `scrapy crawl` launched
// through the same /api/crawls endpoint (with tender_mode=true) and the same
// one-crawl-at-a-time rule.
//
// Tags are deliberately shown above the launch form: add what you're looking
// for first, so a crawl's automatic classification (see TenderLaunchForm's
// pipeline stepper) has something to classify against the moment it finishes.
export default function TendersPage({ prefillSeed }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [focus, setFocus] = useState({ entity: null, runId: null });
  const [pipelineStatus, setPipelineStatus] = useState(null);

  const handleLaunched = (status) => {
    setRefreshKey((k) => k + 1);
    // jump straight to the run that just finished instead of leaving
    // whatever bank/run was previously selected in the results view below
    setFocus({ entity: status.entity, runId: status.run_id });
  };

  return (
    <div className="space-y-6">
      <TenderTagsPanel />
      <TenderLaunchForm prefillSeed={prefillSeed} onLaunched={handleLaunched} onPipelineUpdate={setPipelineStatus} />
      <TenderResultsView
        refreshKey={refreshKey}
        focusEntity={focus.entity}
        focusRunId={focus.runId}
        pipelineStatus={pipelineStatus}
      />
    </div>
  );
}
