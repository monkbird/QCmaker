import type { WizardState } from '../context/wizardTypes'

// Editing and source collection do not require an AI service or a dataset.
// Only the retained legacy discussion needs its confirmed tabular input.
export const routeForState = (path: string, state: WizardState): string | null => {
  if (path !== '/discussion') return null
  if (!state.topic) return '/topic'
  if (!state.dataRef || state.datasetRevision === null || !state.dataConfirmed) return '/data'
  return null
}
