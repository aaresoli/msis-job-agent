/**
 * studentProfiles.js
 * MSIS AI Job Agent — Student Profile Schema v1
 * Sprint 1 · Task S1-23 · Sang · Due: June 11, 2026
 *
 * Exports
 *   ENUMS            – constrained vocabulary for every dropdown / checkbox field
 *   createProfile()  – factory that validates and stamps system fields
 *   validateProfile()– standalone validator; returns { valid, errors }
 *   SAMPLE_PROFILES  – 6 ready-to-use profiles covering all concentrations,
 *                      both academic stages, and both work-auth paths
 */

"use strict";

// ─── Enums ────────────────────────────────────────────────────────────────────
// Mirror the dropdown options from the Sprint 1 schema document exactly.

export const CONCENTRATION = Object.freeze({
  DIGITAL_TRANSFORMATION: "Digital Transformation with AI",
  DATA_ANALYTICS:         "Data Analytics and AI",
  CYBERSECURITY:          "Cybersecurity",
  IS_RESEARCH:            "Information Systems Research in AI",
});

export const ACADEMIC_STAGE = Object.freeze({
  INCOMING:   "Incoming student (Fall)",
  RETURNING:  "Returning / finishing up",
});

export const TARGET_ROLE = Object.freeze({
  IT_CONSULTANT:    "IT Consultant / Tech Risk",
  DATA_ANALYST:     "Data Analyst / BI Engineer",
  CYBERSECURITY:    "Cybersecurity Analyst",
  PM:               "Product / Project Manager",
  SOFTWARE_ENGINEER:"Software Engineer",
  OTHER:            "Other",
});

export const WORK_AUTH = Object.freeze({
  CITIZEN_OR_GC:  "U.S. Citizen / Green Card",
  NEEDS_CPT_OPT:  "Need CPT / OPT sponsorship",
});

export const GEO_PREFERENCE = Object.freeze({
  MIDWEST:         "Midwest (Chicago, Indy, Cincy)",
  EAST_COAST:      "East Coast (NYC, Boston, DC)",
  SOUTH_SOUTHWEST: "South/Southwest (Austin, Dallas, Atlanta)",
  WEST_COAST:      "West Coast (SF, Seattle, LA)",
  ANYWHERE:        "Open to anywhere",
  REMOTE_ONLY:     "Remote only",
});

export const REMOTE_PREFERENCE = Object.freeze({
  REMOTE_ONLY:    "Remote only",
  HYBRID:         "Hybrid is fine",
  ON_SITE:        "On-site is fine",
  NO_PREFERENCE:  "No preference",
});

export const DELIVERY_PREFERENCE = Object.freeze({
  DASHBOARD: "Dashboard / spreadsheet view",
  EMAIL:     "Daily or weekly email",
  SLACK:     "Slack / Teams message",
  PUSH:      "Push notification",
});

export const MATCH_FREQUENCY = Object.freeze({
  REAL_TIME: "Real-time (as they're posted)",
  DAILY:     "Once a day",
  WEEKLY:    "Once a week",
});

// Convenience lookup sets used by the validator.
const _VALID = {
  concentration:       new Set(Object.values(CONCENTRATION)),
  academic_stage:      new Set(Object.values(ACADEMIC_STAGE)),
  target_role:         new Set(Object.values(TARGET_ROLE)),
  work_auth_status:    new Set(Object.values(WORK_AUTH)),
  geo_preference:      new Set(Object.values(GEO_PREFERENCE)),
  remote_preference:   new Set(Object.values(REMOTE_PREFERENCE)),
  delivery_preference: new Set(Object.values(DELIVERY_PREFERENCE)),
  match_frequency:     new Set(Object.values(MATCH_FREQUENCY)),
};

// ─── Validator ────────────────────────────────────────────────────────────────

/**
 * Validate a raw profile object against the v1 schema rules.
 *
 * @param {object} profile
 * @returns {{ valid: boolean, errors: string[] }}
 */
export function validateProfile(profile) {
  const errors = [];

  // Required scalar fields
  const requiredScalars = [
    "concentration", "academic_stage", "work_auth_status",
    "delivery_preference", "profile_version", "updated_at", "ai_matching_consent",
  ];
  for (const field of requiredScalars) {
    if (profile[field] === undefined || profile[field] === null) {
      errors.push(`Missing required field: ${field}`);
    }
  }

  // Enum checks
  if (profile.concentration && !_VALID.concentration.has(profile.concentration)) {
    errors.push(`Invalid concentration: "${profile.concentration}"`);
  }
  if (profile.academic_stage && !_VALID.academic_stage.has(profile.academic_stage)) {
    errors.push(`Invalid academic_stage: "${profile.academic_stage}"`);
  }
  if (profile.work_auth_status && !_VALID.work_auth_status.has(profile.work_auth_status)) {
    errors.push(`Invalid work_auth_status: "${profile.work_auth_status}"`);
  }
  if (profile.delivery_preference && !_VALID.delivery_preference.has(profile.delivery_preference)) {
    errors.push(`Invalid delivery_preference: "${profile.delivery_preference}"`);
  }
  if (profile.match_frequency && !_VALID.match_frequency.has(profile.match_frequency)) {
    errors.push(`Invalid match_frequency: "${profile.match_frequency}"`);
  }
  if (profile.remote_preference != null && !_VALID.remote_preference.has(profile.remote_preference)) {
    errors.push(`Invalid remote_preference: "${profile.remote_preference}"`);
  }

  // target_roles — required array with at least one valid entry
  if (!Array.isArray(profile.target_roles) || profile.target_roles.length === 0) {
    errors.push("target_roles must be a non-empty array");
  } else {
    profile.target_roles.forEach((r) => {
      if (!_VALID.target_role.has(r)) errors.push(`Invalid target_role: "${r}"`);
    });
  }

  // geo_preference — required array with at least one valid entry
  if (!Array.isArray(profile.geo_preference) || profile.geo_preference.length === 0) {
    errors.push("geo_preference must be a non-empty array");
  } else {
    profile.geo_preference.forEach((g) => {
      if (!_VALID.geo_preference.has(g)) errors.push(`Invalid geo_preference: "${g}"`);
    });
  }

  // skills — optional, but each entry must be a non-empty string if present
  if (profile.skills !== undefined) {
    if (!Array.isArray(profile.skills)) {
      errors.push("skills must be an array");
    } else {
      profile.skills.forEach((s, i) => {
        if (typeof s !== "string" || s.trim() === "") {
          errors.push(`skills[${i}] must be a non-empty string`);
        }
      });
    }
  }

  // Conditional: opt_eligibility_date required when needs CPT/OPT
  if (profile.work_auth_status === WORK_AUTH.NEEDS_CPT_OPT) {
    if (!profile.opt_eligibility_date) {
      errors.push("opt_eligibility_date is required when work_auth_status is 'Need CPT / OPT sponsorship'");
    } else if (!/^\d{4}-\d{2}-\d{2}$/.test(profile.opt_eligibility_date)) {
      errors.push("opt_eligibility_date must be in YYYY-MM-DD format");
    }
  }

  // System fields
  if (typeof profile.profile_version !== "number" || profile.profile_version < 1) {
    errors.push("profile_version must be an integer >= 1");
  }
  if (typeof profile.updated_at !== "string" || isNaN(Date.parse(profile.updated_at))) {
    errors.push("updated_at must be a valid ISO-8601 date-time string");
  }
  if (typeof profile.ai_matching_consent !== "boolean") {
    errors.push("ai_matching_consent must be a boolean");
  }

  return { valid: errors.length === 0, errors };
}

// ─── Factory ──────────────────────────────────────────────────────────────────

/**
 * Create and validate a StudentProfile.
 * Stamps system fields (profile_version, updated_at) with defaults if omitted.
 * Throws if the resulting profile is invalid.
 *
 * @param {object} data  – partial profile supplied by the caller
 * @returns {object}     – complete, validated profile object
 */
export function createProfile(data) {
  const profile = {
    // Defaults for optional / system fields
    skills:              [],
    opt_eligibility_date: null,
    remote_preference:   null,
    match_frequency:     MATCH_FREQUENCY.DAILY,
    ai_matching_consent: false,
    profile_version:     1,
    updated_at:          new Date().toISOString(),

    // Caller-supplied fields (overrides defaults above)
    ...data,
  };

  const { valid, errors } = validateProfile(profile);
  if (!valid) {
    throw new Error(
      `Invalid StudentProfile for "${profile.name ?? "unknown"}":\n  - ${errors.join("\n  - ")}`
    );
  }

  return Object.freeze(profile);
}

// ─── Sample Profiles ──────────────────────────────────────────────────────────
// 6 profiles covering:
//   • All 4 concentrations
//   • Both academic stages (Incoming / Returning)
//   • Both work-auth paths (Citizen/GC and CPT/OPT)
//   • All 4 delivery preferences
//   • Mix of geo and remote preferences
//   • One profile with ai_matching_consent: false (setup incomplete)

export const SAMPLE_PROFILES = Object.freeze([

  // 1. Returning · Data Analytics · Citizen · Dashboard
  createProfile({
    name:                "Priya Sharma",
    concentration:       CONCENTRATION.DATA_ANALYTICS,
    academic_stage:      ACADEMIC_STAGE.RETURNING,
    target_roles:        [TARGET_ROLE.DATA_ANALYST, TARGET_ROLE.PM],
    skills:              ["Python", "SQL", "Tableau", "Power BI", "Excel"],
    work_auth_status:    WORK_AUTH.CITIZEN_OR_GC,
    geo_preference:      [GEO_PREFERENCE.MIDWEST, GEO_PREFERENCE.EAST_COAST],
    remote_preference:   REMOTE_PREFERENCE.HYBRID,
    delivery_preference: DELIVERY_PREFERENCE.DASHBOARD,
    match_frequency:     MATCH_FREQUENCY.DAILY,
    ai_matching_consent: true,
    profile_version:     1,
    updated_at:          "2026-05-15T10:00:00Z",
  }),

  // 2. Incoming · Digital Transformation · Needs OPT · Email
  createProfile({
    name:                 "Wei Zhang",
    concentration:        CONCENTRATION.DIGITAL_TRANSFORMATION,
    academic_stage:       ACADEMIC_STAGE.INCOMING,
    target_roles:         [TARGET_ROLE.IT_CONSULTANT, TARGET_ROLE.SOFTWARE_ENGINEER],
    skills:               ["Java", "Agile", "Jira", "AWS", "Process Modeling"],
    work_auth_status:     WORK_AUTH.NEEDS_CPT_OPT,
    opt_eligibility_date: "2026-08-15",
    geo_preference:       [GEO_PREFERENCE.ANYWHERE],
    remote_preference:    REMOTE_PREFERENCE.NO_PREFERENCE,
    delivery_preference:  DELIVERY_PREFERENCE.EMAIL,
    match_frequency:      MATCH_FREQUENCY.WEEKLY,
    ai_matching_consent:  true,
    profile_version:      1,
    updated_at:           "2026-05-20T09:00:00Z",
  }),

  // 3. Returning · Cybersecurity · Citizen · Slack / real-time
  createProfile({
    name:                "Jordan Hayes",
    concentration:       CONCENTRATION.CYBERSECURITY,
    academic_stage:      ACADEMIC_STAGE.RETURNING,
    target_roles:        [TARGET_ROLE.CYBERSECURITY, TARGET_ROLE.IT_CONSULTANT],
    skills:              ["SIEM", "NIST Framework", "Python", "Risk Management", "Splunk"],
    work_auth_status:    WORK_AUTH.CITIZEN_OR_GC,
    geo_preference:      [GEO_PREFERENCE.EAST_COAST, GEO_PREFERENCE.MIDWEST],
    remote_preference:   REMOTE_PREFERENCE.ON_SITE,
    delivery_preference: DELIVERY_PREFERENCE.SLACK,
    match_frequency:     MATCH_FREQUENCY.REAL_TIME,
    ai_matching_consent: true,
    profile_version:     2,
    updated_at:          "2026-05-22T14:30:00Z",
  }),

  // 4. Incoming · IS Research · Needs OPT · Dashboard
  createProfile({
    name:                 "Aisha Nwosu",
    concentration:        CONCENTRATION.IS_RESEARCH,
    academic_stage:       ACADEMIC_STAGE.INCOMING,
    target_roles:         [TARGET_ROLE.DATA_ANALYST, TARGET_ROLE.OTHER],
    skills:               ["R", "Python", "Research Methods", "NLP", "Literature Review"],
    work_auth_status:     WORK_AUTH.NEEDS_CPT_OPT,
    opt_eligibility_date: "2027-01-10",
    geo_preference:       [GEO_PREFERENCE.EAST_COAST, GEO_PREFERENCE.WEST_COAST],
    remote_preference:    REMOTE_PREFERENCE.HYBRID,
    delivery_preference:  DELIVERY_PREFERENCE.DASHBOARD,
    match_frequency:      MATCH_FREQUENCY.WEEKLY,
    ai_matching_consent:  true,
    profile_version:      1,
    updated_at:           "2026-05-25T08:45:00Z",
  }),

  // 5. Returning · Digital Transformation · Citizen · Remote-only / Email
  createProfile({
    name:                "Marcus Bell",
    concentration:       CONCENTRATION.DIGITAL_TRANSFORMATION,
    academic_stage:      ACADEMIC_STAGE.RETURNING,
    target_roles:        [TARGET_ROLE.PM, TARGET_ROLE.IT_CONSULTANT],
    skills:              ["PMP", "Scrum", "Salesforce", "Excel", "Stakeholder Management"],
    work_auth_status:    WORK_AUTH.CITIZEN_OR_GC,
    geo_preference:      [GEO_PREFERENCE.REMOTE_ONLY],
    remote_preference:   REMOTE_PREFERENCE.REMOTE_ONLY,
    delivery_preference: DELIVERY_PREFERENCE.EMAIL,
    match_frequency:     MATCH_FREQUENCY.DAILY,
    ai_matching_consent: true,
    profile_version:     1,
    updated_at:          "2026-05-28T11:00:00Z",
  }),

  // 6. Incoming · Data Analytics · Citizen · Push — consent NOT yet given
  createProfile({
    name:                "Sofia Reyes",
    concentration:       CONCENTRATION.DATA_ANALYTICS,
    academic_stage:      ACADEMIC_STAGE.INCOMING,
    target_roles:        [TARGET_ROLE.DATA_ANALYST],
    skills:              ["SQL", "Tableau", "Excel"],
    work_auth_status:    WORK_AUTH.CITIZEN_OR_GC,
    geo_preference:      [GEO_PREFERENCE.SOUTH_SOUTHWEST, GEO_PREFERENCE.ANYWHERE],
    remote_preference:   REMOTE_PREFERENCE.HYBRID,
    delivery_preference: DELIVERY_PREFERENCE.PUSH,
    match_frequency:     MATCH_FREQUENCY.DAILY,
    ai_matching_consent: false,   // Has not completed setup yet — agent will not run
    profile_version:     1,
    updated_at:          "2026-05-29T07:00:00Z",
  }),

]);

// ─── Quick self-test (runs when executed directly, e.g. `node studentProfiles.js`) ──
if (typeof process !== "undefined" && process.argv[1]?.endsWith("studentProfiles.js")) {
  console.log(`\n✅  Loaded ${SAMPLE_PROFILES.length} sample profiles:\n`);
  for (const p of SAMPLE_PROFILES) {
    const consent = p.ai_matching_consent ? "active" : "pending";
    console.log(`  • ${p.name.padEnd(18)} | ${p.concentration.padEnd(38)} | ${p.academic_stage.padEnd(26)} | consent: ${consent}`);
  }

  // Validate each one
  let allValid = true;
  for (const p of SAMPLE_PROFILES) {
    const { valid, errors } = validateProfile(p);
    if (!valid) {
      console.error(`\n❌  ${p.name}: ${errors.join(", ")}`);
      allValid = false;
    }
  }
  if (allValid) console.log("\n✅  All profiles pass schema validation.\n");
}