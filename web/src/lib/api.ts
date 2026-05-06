const BASE = '';

async function request(path: string, options: RequestInit = {}) {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	if (options.headers) {
		Object.assign(headers, options.headers);
	}

	const resp = await fetch(`${BASE}${path}`, { ...options, headers });
	if (!resp.ok) {
		let msg: string;
		try {
			const data = await resp.json();
			msg = data.detail || data.message || resp.statusText;
		} catch {
			msg = await resp.text() || resp.statusText;
		}
		throw new Error(msg);
	}
	return resp.json();
}

export async function fetchConfig() {
	return request('/api/config');
}

export async function updateConfig(config: Record<string, unknown>) {
	return request('/api/config', {
		method: 'PUT',
		body: JSON.stringify(config)
	});
}

export async function fetchResume(): Promise<{ content: string; path: string }> {
	return request('/api/resume');
}

export async function updateResume(content: string) {
	return request('/api/resume', {
		method: 'PUT',
		body: JSON.stringify({ content })
	});
}

export async function fetchJobs(): Promise<{ threshold: number; groups: Record<string, Job[]> }> {
	return request('/api/jobs');
}

export async function startSearch() {
	return request('/api/search', { method: 'POST' });
}

export async function getSearchStatus(): Promise<SearchStatus> {
	return request('/api/search/status');
}

export async function tailorJob(jobId: number) {
	return request(`/api/jobs/${jobId}/tailor`, { method: 'POST' });
}

export async function updateJobStatus(jobId: number, status: 'open' | 'applied' | 'dismissed') {
	return request(`/api/jobs/${jobId}`, {
		method: 'PATCH',
		body: JSON.stringify({ status })
	});
}

export async function extractJob(url: string): Promise<{
	title: string;
	company: string;
	description: string;
	location: string;
}> {
	return request('/api/jobs/extract', {
		method: 'POST',
		body: JSON.stringify({ url })
	});
}

export async function addManualJob(data: {
	url?: string;
	title?: string;
	company?: string;
	description?: string;
	location?: string;
}): Promise<{ status: string; job_id: number }> {
	return request('/api/jobs', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export async function discoverCompany(company: string): Promise<{
	status: string;
	source?: string;
	board_token?: string;
	url?: string;
	confidence?: string;
	message: string;
}> {
	return request('/api/companies/discover', {
		method: 'POST',
		body: JSON.stringify({ company })
	});
}

export async function generateFromResume(
	resumeText: string
): Promise<{ profile: string; target_roles: string; search_queries: string[] }> {
	return request('/api/generate-profile', {
		method: 'POST',
		body: JSON.stringify({ resume: resumeText })
	});
}

export interface Job {
	id: number;
	title: string;
	company: string;
	description: string;
	url: string;
	source: string;
	location: string;
	category: string;
	salary: string;
	posted_date: string;
	found_date: string;
	score: number;
	reason: string;
	gaps: string;
	has_application: number;
	status: string;
}

export interface SearchStatus {
	status: string;
	message: string;
	progress: number;
	jobs_found: number;
	matches: number;
	errors: string[];
}

export interface RemoteCompany {
	name: string;
	slug: string;
	website: string;
	careers_url: string;
	region: string;
	remote_policy: string;
	company_size: string;
	technologies: string[];
}

export async function fetchRemoteCompanies(): Promise<{
	companies: RemoteCompany[];
	available_technologies: string[];
}> {
	return request('/api/remoteintech/companies');
}

export async function matchTechnologies(): Promise<{
	matched_technologies: string[];
}> {
	return request('/api/remoteintech/match-technologies', { method: 'POST' });
}

export async function addRemoteCompanies(
	companies: { name: string; careers_url: string }[]
): Promise<{ results: { name: string; status: string; message: string }[] }> {
	return request('/api/remoteintech/add-companies', {
		method: 'POST',
		body: JSON.stringify({ companies })
	});
}
