<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchJobs, startSearch, getSearchStatus, tailorJob, addManualJob, extractJob, updateJobStatus, type Job } from '$lib/api';

	let allJobs: Record<string, Job[]> = $state({});
	let threshold = $state(55);
	let searchStatus = $state({ status: 'idle', message: '', progress: 0, jobs_found: 0, matches: 0 });
	let expandedJob: number | null = $state(null);
	let tailoringJob: number | null = $state(null);
	let pollTimer: ReturnType<typeof setInterval> | null = $state(null);
	let showRejected = $state(false);
	let showDismissed = $state(false);
	let tailorError = $state('');

	let showAddModal = $state(false);
	let addForm = $state({ url: '', title: '', company: '', description: '', location: '' });
	let adding = $state(false);
	let extracting = $state(false);
	let addError = $state('');

	const matchedJobs = $derived.by(() => {
		const result: Record<string, Job[]> = {};
		for (const [dt, jobs] of Object.entries(allJobs)) {
			const matched = jobs.filter((j) => j.status !== 'dismissed' && (j.score >= threshold || j.source === 'manual'));
			if (matched.length > 0) result[dt] = matched;
		}
		return result;
	});

	const rejectedJobs = $derived.by(() => {
		const list: Job[] = [];
		for (const jobs of Object.values(allJobs)) {
			for (const j of jobs) {
				if (j.status !== 'dismissed' && j.score > 0 && j.score < threshold && j.source !== 'manual') list.push(j);
			}
		}
		return list.sort((a, b) => b.score - a.score);
	});

	const dismissedJobs = $derived.by(() => {
		const list: Job[] = [];
		for (const jobs of Object.values(allJobs)) {
			for (const j of jobs) {
				if (j.status === 'dismissed') list.push(j);
			}
		}
		return list.sort((a, b) => b.score - a.score);
	});

	const dates = $derived(Object.keys(allJobs).sort().reverse());

	onMount(async () => {
		await loadJobs();
		const status = await getSearchStatus();
		if (status.status === 'running') {
			searchStatus = status;
			startPolling();
		}
	});

	async function loadJobs() {
		const data = await fetchJobs();
		allJobs = data.groups;
		threshold = data.threshold;
	}

	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(async () => {
			searchStatus = await getSearchStatus();
			if (searchStatus.status === 'done' || searchStatus.status === 'error') {
				if (pollTimer) clearInterval(pollTimer);
				pollTimer = null;
				if (searchStatus.status === 'done') await loadJobs();
			}
		}, 2000);
	}

	async function runSearch() {
		try {
			await startSearch();
			searchStatus = { status: 'running', message: 'Starting...', progress: 0, jobs_found: 0, matches: 0 };
			startPolling();
		} catch (e: any) {
			searchStatus = { ...searchStatus, status: 'error', message: e.message };
		}
	}

	async function handleTailor(jobId: number) {
		tailoringJob = jobId;
		for (const jobs of Object.values(allJobs)) {
			const job = jobs.find((j) => j.id === jobId);
			if (job) { job.has_application = 0; break; }
		}
		tailorError = '';
		try {
			await tailorJob(jobId);
			await loadJobs();
		} catch (e: any) {
			tailorError = e.message;
		} finally {
			tailoringJob = null;
		}
	}

	function toggleExpand(jobId: number) {
		expandedJob = expandedJob === jobId ? null : jobId;
	}

	async function handleFetchUrl() {
		if (!addForm.url.trim()) {
			addError = 'Enter a job posting URL.';
			return;
		}
		extracting = true;
		addError = '';
		try {
			const result = await extractJob(addForm.url.trim());
			addForm.title = result.title || addForm.title;
			addForm.company = result.company || addForm.company;
			addForm.description = result.description || addForm.description;
			addForm.location = result.location || addForm.location;
		} catch (e: any) {
			addError = e.message;
		} finally {
			extracting = false;
		}
	}

	async function handleAddJob() {
		addError = '';
		if (!addForm.title.trim() || !addForm.company.trim()) {
			addError = 'Title and company are required. Use "Fetch" to extract from a URL.';
			return;
		}
		adding = true;
		try {
			await addManualJob(addForm);
			showAddModal = false;
			addForm = { url: '', title: '', company: '', description: '', location: '' };
			await loadJobs();
		} catch (e: any) {
			addError = e.message;
		} finally {
			adding = false;
		}
	}

	async function setStatus(jobId: number, status: 'open' | 'applied' | 'dismissed') {
		await updateJobStatus(jobId, status);
		await loadJobs();
	}

	function formatDate(iso: string): string {
		const d = new Date(iso + 'T00:00:00');
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const diff = Math.floor((today.getTime() - d.getTime()) / 86400000);
		if (diff === 0) return 'Today';
		if (diff === 1) return 'Yesterday';
		return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
	}
</script>

<div class="page">
	<div class="header">
		<h1>Jobs</h1>
		<div style="display: flex; gap: 8px;">
			<button class="btn btn-outline" onclick={() => { showAddModal = true; addError = ''; }}>
				Add Job
			</button>
			<button class="btn btn-primary" onclick={runSearch} disabled={searchStatus.status === 'running'}>
				{searchStatus.status === 'running' ? 'Searching...' : 'Run Search'}
			</button>
		</div>
	</div>

	{#if searchStatus.status === 'running' || searchStatus.status === 'starting'}
		<div class="search-progress">
			<div class="progress-bar">
				<div class="progress-fill" style="width: {searchStatus.progress}%"></div>
			</div>
			<p>{searchStatus.message}</p>
		</div>
	{/if}

	{#if searchStatus.status === 'done' && searchStatus.message}
		<div class="alert alert-success">{searchStatus.message}</div>
	{/if}

	{#if searchStatus.status === 'error'}
		<div class="alert alert-error">{searchStatus.message}</div>
	{/if}

	{#if tailorError}
		<div class="alert alert-error">{tailorError}</div>
	{/if}

	{#if dates.length === 0 && rejectedJobs.length === 0 && searchStatus.status !== 'running'}
		<div class="empty">
			<p>No jobs found yet. Click "Run Search" to start.</p>
			<p style="margin-top: 8px; font-size: 13px;">Make sure your API keys and profile are configured in Settings.</p>
		</div>
	{/if}

	{#each dates as dt}
		<div class="date-group">
			<h2>{formatDate(dt)}</h2>
			{#if !matchedJobs[dt] || matchedJobs[dt].length === 0}
				<p class="empty-day">No new matches for this day.</p>
			{/if}
			<div class="job-list">
				{#each matchedJobs[dt] || [] as job}
					<div class="job-card">
						<div class="job-header" onclick={() => toggleExpand(job.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && toggleExpand(job.id)}>
							<div class="job-info">
								<h3>
									{#if job.status === 'applied'}<span class="status-badge applied">Applied</span>{/if}
									{job.title}
								</h3>
								<span class="company">{job.company}</span>
							</div>
							<div class="job-meta">
								<span class="score" class:high={job.score >= 80} class:mid={job.score >= 60 && job.score < 80}>
									{job.score}
								</span>
								{#if job.salary}
									<span class="salary">{job.salary}</span>
								{/if}
								{#if job.location}
									<span class="location">{job.location}</span>
								{/if}
								<span class="source">{job.source}</span>
							</div>
						</div>

						{#if expandedJob === job.id}
							<div class="job-details">
								<div class="detail-section">
									<h4>Why it fits</h4>
									<p>{job.reason}</p>
								</div>
								{#if job.gaps}
									<div class="detail-section">
										<h4>Potential gaps</h4>
										<p>{job.gaps}</p>
									</div>
								{/if}
								<div class="job-actions">
									<a href={job.url} target="_blank" rel="noopener noreferrer" class="btn btn-outline">
										View Listing
									</a>
									{#if job.has_application}
										<a href="/api/jobs/{job.id}/resume.pdf" class="btn btn-outline" download>
											Resume PDF
										</a>
										<a href="/api/jobs/{job.id}/cover-letter.pdf" class="btn btn-outline" download>
											Cover Letter PDF
										</a>
										<button
											class="btn btn-outline"
											onclick={() => handleTailor(job.id)}
											disabled={tailoringJob === job.id}
										>
											{tailoringJob === job.id ? 'Regenerating...' : 'Regenerate'}
										</button>
									{:else}
										<button
											class="btn btn-primary"
											onclick={() => handleTailor(job.id)}
											disabled={tailoringJob === job.id}
										>
											{tailoringJob === job.id ? 'Preparing...' : 'Prepare Application'}
										</button>
									{/if}
									<span class="actions-separator"></span>
									{#if job.status !== 'applied'}
										<button class="btn btn-outline btn-success" onclick={() => setStatus(job.id, 'applied')}>
											Mark Applied
										</button>
									{:else}
										<button class="btn btn-outline" onclick={() => setStatus(job.id, 'open')}>
											Unmark Applied
										</button>
									{/if}
									<button class="btn btn-outline btn-danger" onclick={() => setStatus(job.id, 'dismissed')}>
										Dismiss
									</button>
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{/each}

	{#if rejectedJobs.length > 0}
		<div class="rejected-section">
			<button class="rejected-toggle" onclick={() => (showRejected = !showRejected)}>
				<span>{showRejected ? '▾' : '▸'} Didn't match ({rejectedJobs.length})</span>
			</button>
			{#if showRejected}
				<div class="job-list" style="margin-top: 12px;">
					{#each rejectedJobs as job}
						<div class="job-card">
							<div class="job-header" onclick={() => toggleExpand(job.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && toggleExpand(job.id)}>
								<div class="job-info">
									<h3>
										{#if job.status === 'applied'}<span class="status-badge applied">Applied</span>{/if}
										{job.title}
									</h3>
									<span class="company">{job.company}</span>
								</div>
								<div class="job-meta">
									<span class="score">
										{job.score}
									</span>
									{#if job.salary}
										<span class="salary">{job.salary}</span>
									{/if}
									{#if job.location}
										<span class="location">{job.location}</span>
									{/if}
									<span class="source">{job.source}</span>
								</div>
							</div>

							{#if expandedJob === job.id}
								<div class="job-details">
									<div class="detail-section">
										<h4>Why it didn't match</h4>
										<p>{job.reason}</p>
									</div>
									{#if job.gaps}
										<div class="detail-section">
											<h4>Potential gaps</h4>
											<p>{job.gaps}</p>
										</div>
									{/if}
									<div class="job-actions">
										<a href={job.url} target="_blank" rel="noopener noreferrer" class="btn btn-outline">
											View Listing
										</a>
										{#if job.has_application}
											<a href="/api/jobs/{job.id}/resume.pdf" class="btn btn-outline" download>
												Resume PDF
											</a>
											<a href="/api/jobs/{job.id}/cover-letter.pdf" class="btn btn-outline" download>
												Cover Letter PDF
											</a>
											<button
												class="btn btn-outline"
												onclick={() => handleTailor(job.id)}
												disabled={tailoringJob === job.id}
											>
												{tailoringJob === job.id ? 'Regenerating...' : 'Regenerate'}
											</button>
										{:else}
											<button
												class="btn btn-primary"
												onclick={() => handleTailor(job.id)}
												disabled={tailoringJob === job.id}
											>
												{tailoringJob === job.id ? 'Preparing...' : 'Prepare Application'}
											</button>
										{/if}
										<span class="actions-separator"></span>
										{#if job.status !== 'applied'}
											<button class="btn btn-outline btn-success" onclick={() => setStatus(job.id, 'applied')}>
												Mark Applied
											</button>
										{:else}
											<button class="btn btn-outline" onclick={() => setStatus(job.id, 'open')}>
												Unmark Applied
											</button>
										{/if}
										<button class="btn btn-outline btn-danger" onclick={() => setStatus(job.id, 'dismissed')}>
											Dismiss
										</button>
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	{#if dismissedJobs.length > 0}
		<div class="rejected-section">
			<button class="rejected-toggle" onclick={() => (showDismissed = !showDismissed)}>
				<span>{showDismissed ? '▾' : '▸'} Dismissed ({dismissedJobs.length})</span>
			</button>
			{#if showDismissed}
				<div class="rejected-list">
					{#each dismissedJobs as job}
						<div class="rejected-row">
							<span class="rejected-score">{job.score}</span>
							<span class="rejected-title">{job.title}</span>
							<span class="rejected-company">{job.company}</span>
							<button class="btn-restore" onclick={() => setStatus(job.id, 'open')}>Restore</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	{#if showAddModal}
		<div class="modal-overlay" onclick={() => (showAddModal = false)} role="presentation">
			<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog">
				<h2>Add Job</h2>

				{#if addError}
					<div class="alert alert-error">{addError}</div>
				{/if}

				<div class="field">
					<label for="add-url">Job posting URL</label>
					<div class="url-field">
						<input id="add-url" type="text" bind:value={addForm.url} placeholder="https://..." />
						<button class="btn btn-outline" onclick={handleFetchUrl} disabled={extracting}>
							{extracting ? 'Fetching...' : 'Fetch'}
						</button>
					</div>
					<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
						Paste a URL and click Fetch to extract details, or fill in manually below.
					</p>
				</div>
				<div class="field">
					<label for="add-title">Title</label>
					<input id="add-title" type="text" bind:value={addForm.title} placeholder="VP Engineering" />
				</div>
				<div class="field">
					<label for="add-company">Company</label>
					<input id="add-company" type="text" bind:value={addForm.company} placeholder="Acme Inc" />
				</div>
				<div class="field">
					<label for="add-location">Location</label>
					<input id="add-location" type="text" bind:value={addForm.location} placeholder="Remote" />
				</div>
				<div class="field">
					<label for="add-desc">Description</label>
					<textarea id="add-desc" bind:value={addForm.description} rows="6" placeholder="Paste the job description..."></textarea>
				</div>

				<div class="modal-actions">
					<button class="btn btn-outline" onclick={() => (showAddModal = false)}>Cancel</button>
					<button class="btn btn-primary" onclick={handleAddJob} disabled={adding}>
						{adding ? 'Adding...' : 'Add Job'}
					</button>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.empty-day {
		font-size: 13px;
		color: var(--text-muted);
		padding: 12px 0;
	}

	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 200;
	}

	.modal {
		background: var(--surface);
		border-radius: var(--radius);
		padding: 24px;
		width: 90%;
		max-width: 520px;
		max-height: 85vh;
		overflow-y: auto;
		box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
	}

	.modal h2 {
		font-size: 18px;
		font-weight: 600;
		margin-bottom: 16px;
	}

	.url-field {
		display: flex;
		gap: 8px;
	}

	.url-field input {
		flex: 1;
	}

	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 16px;
	}

	.rejected-section {
		margin-top: 32px;
		border-top: 1px solid var(--border);
		padding-top: 16px;
	}

	.rejected-toggle {
		background: none;
		border: none;
		font-size: 14px;
		font-weight: 600;
		color: var(--text-muted);
		cursor: pointer;
		padding: 4px 0;
	}

	.rejected-toggle:hover {
		color: var(--text);
	}

	.rejected-list {
		margin-top: 12px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.rejected-row {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-size: 13px;
		padding: 6px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
	}

	.rejected-score {
		font-weight: 700;
		color: var(--text-muted);
		min-width: 24px;
		text-align: right;
	}

	.rejected-title {
		font-weight: 500;
		white-space: nowrap;
	}

	.rejected-company {
		color: var(--text-muted);
		white-space: nowrap;
	}

	.rejected-reason {
		color: var(--text-muted);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.rejected-link {
		color: var(--primary);
		text-decoration: none;
		font-size: 12px;
		flex-shrink: 0;
	}

	.rejected-link:hover {
		text-decoration: underline;
	}

	.status-badge {
		display: inline-block;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.3px;
		padding: 2px 6px;
		border-radius: 4px;
		margin-right: 6px;
		vertical-align: middle;
	}

	.status-badge.applied {
		background: var(--alert-success-bg);
		color: var(--success);
	}

	.actions-separator {
		width: 1px;
		height: 20px;
		background: var(--border);
		margin: 0 4px;
		align-self: center;
	}

	.btn-success {
		color: var(--success) !important;
	}

	.btn-success:hover {
		border-color: var(--success) !important;
	}

	.btn-danger {
		color: var(--error) !important;
	}

	.btn-danger:hover {
		border-color: var(--error) !important;
	}

	.btn-restore {
		background: none;
		border: none;
		color: var(--primary);
		font-size: 12px;
		cursor: pointer;
		padding: 0;
		flex-shrink: 0;
	}

	.btn-restore:hover {
		text-decoration: underline;
	}
</style>
