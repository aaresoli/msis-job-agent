import type { components } from "@/lib/generated/api";

// Discovery shapes are taken straight from the generated OpenAPI types rather
// than re-declared, so a backend field change fails `npm run typecheck`
// instead of silently rendering undefined.
export type DiscoveryJobCard = components["schemas"]["JobCard"];
export type DiscoveryJobsResponse = components["schemas"]["JobsResponse"];
export type DiscoveryFacetCount = components["schemas"]["FacetCount"];
export type DiscoveryTaxonomy = components["schemas"]["TaxonomyResponse"];
export type DiscoveryPostCard = components["schemas"]["PostCard"];
export type DiscoveryPostsResponse = components["schemas"]["PostsResponse"];
export type DiscoveryPostStats = components["schemas"]["PostStatsResponse"];

export type Job = {
  id: string;
  title: string;
  company: string;
  location?: string;
  remote_status?: string;
  posted_at?: string;
  description?: string;
  source: string;
  source_url?: string;
  apply_url?: string;
  concentration_tags: string[];
  opt_cpt_flag?: boolean | null;
  skills?: string[];
};

export type Match = {
  match_id: string;
  score: number;
  confidence?: number;
  explanation?: string;
  status: string;
  job: Job;
};

export type Application = {
  id: string;
  company_name: string;
  role_title: string;
  status: string;
  deadline?: string;
  external_url?: string;
};
