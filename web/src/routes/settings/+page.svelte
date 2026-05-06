<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchConfig, updateConfig, fetchResume, updateResume, generateFromResume, discoverCompany } from '$lib/api';

	let config: Record<string, any> | null = $state(null);
	let resume = $state('');
	let saving = $state(false);
	let saved = $state(false);
	let error = $state('');
	let generating = $state(false);

	let showAnthropicKey = $state(false);
	let showRapidapiKey = $state(false);

	let companyInput = $state('');
	let discovering = $state(false);
	let discoverMessage = $state('');
	let discoverError = $state('');

	const sourceLabels: Record<string, { label: string; hint?: string }> = {
		remotive: { label: 'Remotive' },
		jsearch: { label: 'JSearch (RapidAPI)' },
		greenhouse: { label: 'Greenhouse Boards', hint: 'Filtered by role keywords' },
		lever: { label: 'Lever Boards', hint: 'Filtered by role keywords' },
		career_pages: { label: 'Career Pages', hint: 'Filtered by role keywords' },
		hn_who_is_hiring: { label: 'HN Who is Hiring', hint: 'Filtered by role + startup keywords' },
		yc_jobs: { label: 'YC Jobs', hint: 'Filtered by role + startup keywords' }
	};

	onMount(async () => {
		config = await fetchConfig();
		if (!config!.api_keys) config!.api_keys = { anthropic: '', rapidapi: '' };
		if (!config!.prompts) config!.prompts = {};
		if (config!.pdf_css === undefined) config!.pdf_css = '';
		if (!config!.sources) {
			config!.sources = Object.fromEntries(Object.keys(sourceLabels).map((k) => [k, true]));
		}
		const res = await fetchResume();
		resume = res.content;
	});

	async function save() {
		if (!config) return;
		saving = true;
		saved = false;
		error = '';
		try {
			await updateConfig(config);
			await updateResume(resume);
			saved = true;
			setTimeout(() => (saved = false), 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			saving = false;
		}
	}

	async function handleGenerate() {
		if (!resume.trim()) {
			error = 'Upload or paste a resume first.';
			return;
		}
		generating = true;
		error = '';
		try {
			const result = await generateFromResume(resume);
			if (result.profile) config!.profile = result.profile;
			if (result.target_roles) config!.target_roles = result.target_roles;
			if (result.search_queries) config!.search_queries = result.search_queries;
			await save();
		} catch (e: any) {
			error = e.message;
		} finally {
			generating = false;
		}
	}

	function handleQueriesInput(e: Event) {
		const target = e.target as HTMLTextAreaElement;
		config!.search_queries = target.value
			.split('\n')
			.filter((q: string) => q.trim());
	}

	function handleKeywordsInput(field: 'role_keywords' | 'startup_role_keywords') {
		return (e: Event) => {
			const target = e.target as HTMLTextAreaElement;
			config![field] = target.value
				.split('\n')
				.filter((q: string) => q.trim());
		};
	}

	async function handleFileUpload(e: Event) {
		const target = e.target as HTMLInputElement;
		const file = target.files?.[0];
		if (file) {
			resume = await file.text();
		}
	}

	interface CompanyEntry {
		company: string;
		source: string;
		detail: string;
	}

	const companies = $derived.by((): CompanyEntry[] => {
		if (!config) return [];
		const list: CompanyEntry[] = [];
		for (const b of config.greenhouse_boards || []) {
			list.push({ company: b.company, source: 'Greenhouse', detail: b.board_token });
		}
		for (const b of config.lever_boards || []) {
			list.push({ company: b.company, source: 'Lever', detail: b.board_token });
		}
		for (const p of config.career_pages || []) {
			list.push({ company: p.company, source: 'Career page', detail: p.url });
		}
		list.sort((a, b) => a.company.localeCompare(b.company));
		return list;
	});

	async function handleAddCompany() {
		if (!companyInput.trim()) return;
		discovering = true;
		discoverMessage = '';
		discoverError = '';
		try {
			const result = await discoverCompany(companyInput.trim());
			discoverMessage = result.message;
			companyInput = '';
			config = await fetchConfig();
			if (!config!.api_keys) config!.api_keys = { anthropic: '', rapidapi: '' };
			if (!config!.prompts) config!.prompts = {};
			if (config!.pdf_css === undefined) config!.pdf_css = '';
			if (!config!.sources) {
				config!.sources = Object.fromEntries(Object.keys(sourceLabels).map((k) => [k, true]));
			}
			setTimeout(() => (discoverMessage = ''), 5000);
		} catch (e: any) {
			discoverError = e.message;
		} finally {
			discovering = false;
		}
	}

	function removeCompany(company: string) {
		if (!config) return;
		config.greenhouse_boards = (config.greenhouse_boards || []).filter((b: any) => b.company !== company);
		config.lever_boards = (config.lever_boards || []).filter((b: any) => b.company !== company);
		config.career_pages = (config.career_pages || []).filter((p: any) => p.company !== company);
	}
</script>

<div class="page">
	<div class="header">
		<h1>Settings</h1>
		<button class="btn btn-primary" onclick={save} disabled={saving}>
			{saving ? 'Saving...' : 'Save'}
		</button>
	</div>

	{#if saved}
		<div class="alert alert-success">Settings saved.</div>
	{/if}
	{#if error}
		<div class="alert alert-error">{error}</div>
	{/if}

	{#if config}
		<div class="settings-grid">
			<section class="card">
				<h2>API Keys</h2>
				<div class="field">
					<label for="anthropic-key">Anthropic API Key</label>
					<div class="key-field">
						<input
							id="anthropic-key"
							type={showAnthropicKey ? 'text' : 'password'}
							bind:value={config.api_keys.anthropic}
							placeholder="sk-ant-..."
						/>
						<button class="btn-icon" onclick={() => (showAnthropicKey = !showAnthropicKey)}>
							{showAnthropicKey ? 'Hide' : 'Show'}
						</button>
					</div>
					{#if config.api_keys.anthropic_env}
						<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
							Set via environment variable
						</p>
					{/if}
				</div>
				<div class="field">
					<label for="rapidapi-key">RapidAPI Key (optional, enables JSearch)</label>
					<div class="key-field">
						<input
							id="rapidapi-key"
							type={showRapidapiKey ? 'text' : 'password'}
							bind:value={config.api_keys.rapidapi}
							placeholder="Optional"
						/>
						<button class="btn-icon" onclick={() => (showRapidapiKey = !showRapidapiKey)}>
							{showRapidapiKey ? 'Hide' : 'Show'}
						</button>
					</div>
					{#if config.api_keys.rapidapi_env}
						<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
							Set via environment variable
						</p>
					{/if}
				</div>
			</section>

			<section class="card">
				<h2>Resume</h2>
				<div class="field">
					<label for="resume-text">Resume content (Markdown)</label>
					<textarea id="resume-text" bind:value={resume} rows="20" class="mono"></textarea>
				</div>
				<div class="field">
					<label for="resume-file">Or upload a file (.md, .txt)</label>
					<input id="resume-file" type="file" accept=".md,.txt" onchange={handleFileUpload} />
				</div>
			</section>

			<section class="card">
				<h2>Profile</h2>
				<div style="display: flex; justify-content: flex-end; margin-bottom: 12px;">
					<button class="btn btn-outline" onclick={handleGenerate} disabled={generating}>
						{generating ? 'Generating...' : 'Generate from Resume'}
					</button>
				</div>
				<div class="field">
					<label for="profile">Your background (used for matching and cover letters)</label>
					<textarea id="profile" bind:value={config.profile} rows="8"></textarea>
				</div>
				<div class="field">
					<label for="target-roles">Target roles</label>
					<textarea id="target-roles" bind:value={config.target_roles} rows="6"></textarea>
				</div>
			</section>

			<section class="card">
				<h2>Search</h2>
				<div class="field">
					<label for="location">Location</label>
					<input id="location" type="text" bind:value={config.location} placeholder="remote" />
					<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
						"remote" filters for remote-only jobs. Any other value (e.g. "San Francisco, CA") searches that area.
					</p>
				</div>
				<div class="field">
					<label for="model">AI Model</label>
					<input id="model" type="text" bind:value={config.model} />
				</div>
				<div class="field">
					<label for="threshold">Match threshold (0-100)</label>
					<input id="threshold" type="number" bind:value={config.match_threshold} min="0" max="100" />
				</div>
				<div class="field">
					<label for="queries">Search queries (one per line)</label>
					<textarea
						id="queries"
						rows="6"
						value={config.search_queries?.join('\n') || ''}
						oninput={handleQueriesInput}
					></textarea>
				</div>
				<div class="field">
					<label for="role-keywords">Role keywords (one per line)</label>
					<textarea
						id="role-keywords"
						rows="5"
						value={config.role_keywords?.join('\n') || ''}
						oninput={handleKeywordsInput('role_keywords')}
					></textarea>
					<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
						Job titles must contain one of these keywords to be included from Greenhouse, Lever, and career page sources.
					</p>
				</div>
				<div class="field">
					<label for="startup-keywords">Startup role keywords (one per line)</label>
					<textarea
						id="startup-keywords"
						rows="3"
						value={config.startup_role_keywords?.join('\n') || ''}
						oninput={handleKeywordsInput('startup_role_keywords')}
					></textarea>
					<p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
						Additional keywords used for HN Who is Hiring and YC Jobs (combined with role keywords above).
					</p>
				</div>
			</section>

			<section class="card">
				<h2>Target Companies</h2>
				<p class="hint">Add companies to monitor. The system will automatically find where they list jobs.</p>

				<div class="company-add">
					<input
						type="text"
						bind:value={companyInput}
						placeholder="e.g. Spotify, Stripe, Anthropic..."
						onkeydown={(e) => e.key === 'Enter' && handleAddCompany()}
					/>
					<button class="btn btn-primary" onclick={handleAddCompany} disabled={discovering}>
						{discovering ? 'Finding...' : 'Add'}
					</button>
				</div>

				{#if discoverError}
					<div class="alert alert-error" style="margin-top: 12px;">{discoverError}</div>
				{/if}
				{#if discoverMessage}
					<div class="alert alert-success" style="margin-top: 12px;">{discoverMessage}</div>
				{/if}

				{#if companies.length > 0}
					<div class="company-list">
						{#each companies as entry}
							<div class="company-row">
								<span class="company-name">{entry.company}</span>
								<span class="company-source">{entry.source}</span>
								<span class="company-detail" title={entry.detail}>{entry.detail}</span>
								<button class="company-remove" onclick={() => removeCompany(entry.company)} title="Remove">×</button>
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<section class="card">
				<h2>Sources</h2>
				<p class="hint">Toggle which job boards and sources to search.</p>
				<div class="source-toggles">
					{#each Object.entries(sourceLabels) as [key, source]}
						<label class="toggle-row">
							<input type="checkbox" bind:checked={config.sources[key]} />
							<span>{source.label}</span>
							{#if source.hint}
								<span class="source-hint">{source.hint}</span>
							{/if}
						</label>
					{/each}
				</div>
			</section>

			<section class="card">
				<h2>Prompts</h2>
				<p class="hint">Control how the AI evaluates jobs and writes application materials.</p>

				<div class="field">
					<label for="prompt-matching">Matching prompt</label>
					<textarea id="prompt-matching" bind:value={config.prompts.matching} rows="12" class="mono"
					></textarea>
				</div>
				<div class="field">
					<label for="prompt-resume">Resume tailoring prompt</label>
					<textarea
						id="prompt-resume"
						bind:value={config.prompts.resume_tailoring}
						rows="10"
						class="mono"
					></textarea>
				</div>
				<div class="field">
					<label for="prompt-cover">Cover letter prompt</label>
					<textarea
						id="prompt-cover"
						bind:value={config.prompts.cover_letter}
						rows="10"
						class="mono"
					></textarea>
				</div>
				<div class="field">
					<label for="prompt-humanize">Humanize prompt (leave empty to skip)</label>
					<textarea
						id="prompt-humanize"
						bind:value={config.prompts.humanize}
						rows="10"
						class="mono"
					></textarea>
				</div>
			</section>

			<section class="card">
				<h2>PDF Styling</h2>
				<p class="hint">Custom CSS for generated resume and cover letter PDFs. Leave empty to use the default stylesheet.</p>
				<div class="field">
					<label for="pdf-css">PDF CSS</label>
					<textarea
						id="pdf-css"
						bind:value={config.pdf_css}
						rows="14"
						class="mono"
						placeholder="/* Custom PDF styles — overrides templates/resume.css */"
					></textarea>
				</div>
			</section>
		</div>
	{/if}
</div>

<style>
	.source-toggles {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.toggle-row {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 14px;
		cursor: pointer;
	}

	.source-hint {
		font-size: 11px;
		color: var(--text-muted);
		font-style: italic;
	}

	.toggle-row input[type='checkbox'] {
		width: 18px;
		height: 18px;
		accent-color: var(--primary);
		cursor: pointer;
	}

	.company-add {
		display: flex;
		gap: 8px;
	}

	.company-add input {
		flex: 1;
		padding: 8px 12px;
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 14px;
		font-family: inherit;
		background: var(--surface);
		color: var(--text);
	}

	.company-add input:focus {
		outline: none;
		border-color: var(--primary);
		box-shadow: 0 0 0 3px var(--primary-soft);
	}

	.company-list {
		margin-top: 16px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.company-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 13px;
	}

	.company-name {
		font-weight: 600;
		min-width: 120px;
	}

	.company-source {
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.3px;
		color: var(--primary);
		background: var(--primary-soft);
		padding: 2px 6px;
		border-radius: 4px;
		white-space: nowrap;
	}

	.company-detail {
		color: var(--text-muted);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.company-remove {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 18px;
		cursor: pointer;
		padding: 0 4px;
		line-height: 1;
		flex-shrink: 0;
	}

	.company-remove:hover {
		color: var(--error);
	}
</style>
