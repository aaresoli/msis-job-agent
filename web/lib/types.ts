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
