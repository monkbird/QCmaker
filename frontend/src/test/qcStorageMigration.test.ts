import { expect, it, vi } from 'vitest'
import { openDB, deleteDB } from 'idb'

it('upgrades a real IndexedDB v1 project while preserving its source blob and history', async () => {
  await deleteDB('qcmaker')
  const old=await openDB('qcmaker',1,{upgrade(db){
    const datasets=db.createObjectStore('datasets',{keyPath:'dataRef'});datasets.createIndex('by-project','projectId')
    db.createObjectStore('discussion_events',{keyPath:['session_id','event_seq']})
    const images=db.createObjectStore('chart_images',{keyPath:'chartImageRef'});images.createIndex('by-project','projectId')
    db.createObjectStore('project_state',{keyPath:'projectId'})
  }})
  await old.put('project_state',{projectId:'old',sessions:['s1'],snapshot:{currentProjectId:'old',dataRef:'data-old',dataConfirmed:true,topic:'历史课题'}})
  await old.put('datasets',{dataRef:'data-old',projectId:'old',sourceFile:new Blob(['原始资料']),filename:'old.csv',revision:3})
  old.close();vi.resetModules()
  const storage=await import('../storage/db')
  const restored=await storage.loadProjectState('old')
  expect(restored?.snapshot?.datasetRefs).toEqual(['data-old'])
  expect(restored?.snapshot?.chapterRefs).toEqual([])
  expect(restored?.snapshot?.dataConfirmed).toBe(true)
  expect(restored?.sessions).toEqual(['s1'])
  expect((await storage.loadDataset('data-old'))?.filename).toBe('old.csv')
})
