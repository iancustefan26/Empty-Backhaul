import {
  FeatureCollection,
  LoadFeature,
  MatchState,
  TruckFeature,
} from "./types";

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* ignore */ }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export const fetchTrucks = () =>
  getJson<FeatureCollection<TruckFeature>>("/api/trucks/live");

export const fetchLoads = () =>
  getJson<FeatureCollection<LoadFeature>>("/api/loads/live");

export const runMatch = (truckId: number, useMockLlm: boolean) =>
  getJson<MatchState>(`/api/match/${truckId}?mock_llm=${useMockLlm}`, {
    method: "POST",
  });
