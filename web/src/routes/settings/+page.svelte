<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchConfig, updateConfig, fetchResume, updateResume, generateFromResume, discoverCompany, fetchRemoteCompanies, matchTechnologies, addRemoteCompanies, type RemoteCompany } from '$lib/api';

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

	let showRemoteBrowser = $state(false);
	let remoteCompanies = $state<RemoteCompany[]>([]);
	let availableTechs = $state<string[]>([]);
	let loadingRemote = $state(false);
	let selectedTechs = $state<Set<string>>(new Set());
	let remoteSearch = $state('');
	let selectedSlugs = $state<Set<string>>(new Set());
	let matchingTechs = $state(false);
	let addingRemote = $state(false);
	let addRemoteMessage = $state('');
	let editingCompany = $state<string | null>(null);

	const sourceLabels: Record<string, { label: string; hint?: string }> = {
		remotive: { label: 'Remotive' },
		jsearch: { label: 'JSearch (RapidAPI)' },
		greenhouse: { label: 'Greenhouse Boards', hint: 'Filtered by role keywords' },
		lever: { label: 'Lever Boards', hint: 'Filtered by role keywords' },
		ashby: { label: 'Ashby Boards', hint: 'Filtered by role keywords' },
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
		for (const b of config.ashby_boards || []) {
			list.push({ company: b.company, source: 'Ashby', detail: b.board_token });
		}
		for (const p of config.career_pages || []) {
			list.push({ company: p.company, source: 'Career page', detail: p.url });
		}
		list.sort((a, b) => a.company.localeCompare(b.company));
		return list;
	});

	const existingCompanyNames = $derived.by((): Set<string> => {
		if (!config) return new Set();
		const names = new Set<string>();
		for (const b of config.greenhouse_boards || []) names.add(b.company.toLowerCase());
		for (const b of config.lever_boards || []) names.add(b.company.toLowerCase());
		for (const b of config.ashby_boards || []) names.add(b.company.toLowerCase());
		for (const p of config.career_pages || []) names.add(p.company.toLowerCase());
		return names;
	});

	const filteredRemote = $derived.by((): RemoteCompany[] => {
		let list = remoteCompanies;
		if (selectedTechs.size > 0) {
			list = list.filter((c) => c.technologies.some((t) => selectedTechs.has(t)));
		}
		if (remoteSearch.trim()) {
			const q = remoteSearch.toLowerCase();
			list = list.filter((c) => c.name.toLowerCase().includes(q));
		}
		return list;
	});

	async function openRemoteBrowser() {
		showRemoteBrowser = !showRemoteBrowser;
		if (showRemoteBrowser && remoteCompanies.length === 0) {
			loadingRemote = true;
			try {
				const data = await fetchRemoteCompanies();
				remoteCompanies = data.companies;
				availableTechs = data.available_technologies;
			} catch (e: any) {
				discoverError = e.message;
			} finally {
				loadingRemote = false;
			}
		}
	}

	async function handleMatchTechs() {
		matchingTechs = true;
		try {
			const result = await matchTechnologies();
			selectedTechs = new Set(result.matched_technologies);
		} catch (e: any) {
			discoverError = e.message;
		} finally {
			matchingTechs = false;
		}
	}

	function toggleTech(tech: string) {
		const next = new Set(selectedTechs);
		if (next.has(tech)) next.delete(tech);
		else next.add(tech);
		selectedTechs = next;
	}

	function toggleSelectCompany(slug: string) {
		const next = new Set(selectedSlugs);
		if (next.has(slug)) next.delete(slug);
		else next.add(slug);
		selectedSlugs = next;
	}

	function selectAllVisible() {
		const next = new Set(selectedSlugs);
		for (const c of filteredRemote) {
			if (!existingCompanyNames.has(c.name.toLowerCase())) next.add(c.slug);
		}
		selectedSlugs = next;
	}

	function deselectAll() {
		selectedSlugs = new Set();
	}

	async function handleAddSelected() {
		const toAdd = filteredRemote
			.filter((c) => selectedSlugs.has(c.slug))
			.map((c) => ({ name: c.name, careers_url: c.careers_url }));
		if (toAdd.length === 0) return;

		addingRemote = true;
		addRemoteMessage = '';
		try {
			const result = await addRemoteCompanies(toAdd);
			addRemoteMessage = `Added ${result.added} of ${toAdd.length} companies.`;
			selectedSlugs = new Set();
			config = await fetchConfig();
			if (!config!.api_keys) config!.api_keys = { anthropic: '', rapidapi: '' };
			if (!config!.prompts) config!.prompts = {};
			if (config!.pdf_css === undefined) config!.pdf_css = '';
			if (!config!.sources) {
				config!.sources = Object.fromEntries(Object.keys(sourceLabels).map((k) => [k, true]));
			}
			setTimeout(() => (addRemoteMessage = ''), 5000);
		} catch (e: any) {
			discoverError = e.message;
		} finally {
			addingRemote = false;
		}
	}

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

	function updateCompanyDetail(company: string, newDetail: string) {
		if (!config) return;
		for (const b of config.greenhouse_boards || []) {
			if (b.company === company) { b.board_token = newDetail; return; }
		}
		for (const b of config.lever_boards || []) {
			if (b.company === company) { b.board_token = newDetail; return; }
		}
		for (const b of config.ashby_boards || []) {
			if (b.company === company) { b.board_token = newDetail; return; }
		}
		for (const p of config.career_pages || []) {
			if (p.company === company) { p.url = newDetail; return; }
		}
	}

	async function removeCompany(company: string) {
		if (!config) return;
		config.greenhouse_boards = (config.greenhouse_boards || []).filter((b: any) => b.company !== company);
		config.lever_boards = (config.lever_boards || []).filter((b: any) => b.company !== company);
		config.ashby_boards = (config.ashby_boards || []).filter((b: any) => b.company !== company);
		config.career_pages = (config.career_pages || []).filter((p: any) => p.company !== company);
		await save();
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
				<p class="hint">Add a company name or paste a job board URL (Greenhouse, Lever, or career page).</p>

				<div class="company-add">
					<input
						type="text"
						bind:value={companyInput}
						placeholder="e.g. Stripe, https://boards.greenhouse.io/stripe..."
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
								{#if editingCompany === entry.company}
									<input
										class="company-detail-input"
										type="text"
										value={entry.detail}
										onblur={async (e) => {
											if (!editingCompany) return;
											updateCompanyDetail(entry.company, (e.target as HTMLInputElement).value);
											editingCompany = null;
											await save();
										}}
										onkeydown={(e) => {
											if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
											if (e.key === 'Escape') { editingCompany = null; }
										}}
										autofocus
									/>
								{:else}
									<span
										class="company-detail"
										title="Click to edit — {entry.detail}"
										onclick={() => (editingCompany = entry.company)}
									>{entry.detail}</span>
								{/if}
								<button class="company-remove" onclick={() => removeCompany(entry.company)} title="Remove">×</button>
							</div>
						{/each}
					</div>
				{/if}

				<div style="margin-top: 16px;">
					<button class="btn btn-outline" onclick={openRemoteBrowser}>
						{showRemoteBrowser ? 'Hide' : 'Browse Remote Companies'}
					</button>
				</div>

				{#if showRemoteBrowser}
					<div class="remote-browser">
						{#if loadingRemote}
							<p class="loading">Loading companies...</p>
						{:else}
							<div class="remote-toolbar">
								<button class="btn btn-outline btn-sm" onclick={handleMatchTechs} disabled={matchingTechs}>
									{matchingTechs ? 'Matching...' : 'Match from Resume'}
								</button>
								<input
									type="text"
									class="remote-search"
									bind:value={remoteSearch}
									placeholder="Filter by name..."
								/>
							</div>

							<div class="tech-pills">
								{#each availableTechs as tech}
									<button
										class="pill"
										class:selected={selectedTechs.has(tech)}
										onclick={() => toggleTech(tech)}
									>{tech}</button>
								{/each}
							</div>

							<div class="remote-actions">
								<span class="remote-count">
									{filteredRemote.length} companies{selectedSlugs.size > 0 ? `, ${selectedSlugs.size} selected` : ''}
								</span>
								<div style="display: flex; gap: 8px;">
									<button class="btn btn-outline btn-sm" onclick={selectAllVisible}>Select all</button>
									{#if selectedSlugs.size > 0}
										<button class="btn btn-outline btn-sm" onclick={deselectAll}>Deselect</button>
										<button class="btn btn-primary btn-sm" onclick={handleAddSelected} disabled={addingRemote}>
											{addingRemote ? 'Adding...' : `Add ${selectedSlugs.size} selected`}
										</button>
									{/if}
								</div>
							</div>

							{#if addRemoteMessage}
								<div class="alert alert-success" style="margin-top: 8px; font-size: 13px;">{addRemoteMessage}</div>
							{/if}

							<div class="remote-list">
								{#each filteredRemote as company (company.slug)}
									{@const isExisting = existingCompanyNames.has(company.name.toLowerCase())}
									<label class="remote-row" class:existing={isExisting}>
										<input
											type="checkbox"
											checked={isExisting || selectedSlugs.has(company.slug)}
											disabled={isExisting}
											onchange={() => toggleSelectCompany(company.slug)}
										/>
										<span class="remote-name">{company.name}</span>
										<span class="remote-meta">{company.remote_policy?.replace('-', ' ') || ''}</span>
										<span class="remote-meta">{company.region?.replace('-', ' ') || ''}</span>
										<span class="remote-techs">
											{#each company.technologies as tech}
												<span class="tech-tag" class:matched={selectedTechs.has(tech)}>{tech}</span>
											{/each}
										</span>
									</label>
								{/each}
							</div>
						{/if}
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
		cursor: pointer;
		border-bottom: 1px dashed transparent;
	}

	.company-detail:hover {
		border-bottom-color: var(--text-muted);
	}

	.company-detail-input {
		flex: 1;
		min-width: 0;
		padding: 2px 6px;
		font-size: 13px;
		font-family: inherit;
		border: 1px solid var(--primary);
		border-radius: 4px;
		background: var(--surface);
		color: var(--text);
		outline: none;
		box-shadow: 0 0 0 2px var(--primary-soft);
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

	.remote-browser {
		margin-top: 16px;
		border-top: 1px solid var(--border);
		padding-top: 16px;
	}

	.remote-toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 12px;
	}

	.remote-search {
		flex: 1;
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 13px;
		background: var(--surface);
		color: var(--text);
	}

	.remote-search:focus {
		outline: none;
		border-color: var(--primary);
		box-shadow: 0 0 0 3px var(--primary-soft);
	}

	.tech-pills {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 12px;
	}

	.pill {
		padding: 3px 10px;
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface);
		color: var(--text-muted);
		font-size: 12px;
		cursor: pointer;
		transition: all 0.15s;
	}

	.pill:hover {
		border-color: var(--primary);
		color: var(--text);
	}

	.pill.selected {
		background: var(--primary);
		color: var(--bg);
		border-color: var(--primary);
		font-weight: 500;
	}

	.remote-actions {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 8px;
	}

	.remote-count {
		font-size: 13px;
		color: var(--text-muted);
	}

	.btn-sm {
		padding: 4px 10px;
		font-size: 12px;
	}

	.remote-list {
		max-height: 400px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 4px;
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 4px;
	}

	.remote-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 8px;
		border-radius: 4px;
		font-size: 13px;
		cursor: pointer;
	}

	.remote-row:hover {
		background: var(--hover-bg);
	}

	.remote-row.existing {
		opacity: 0.5;
	}

	.remote-row input[type='checkbox'] {
		width: 16px;
		height: 16px;
		accent-color: var(--primary);
		flex-shrink: 0;
	}

	.remote-name {
		font-weight: 500;
		min-width: 140px;
	}

	.remote-meta {
		font-size: 11px;
		color: var(--text-muted);
		min-width: 80px;
		text-transform: capitalize;
	}

	.remote-techs {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		flex: 1;
		justify-content: flex-end;
	}

	.tech-tag {
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 8px;
		background: var(--bg);
		border: 1px solid var(--border);
		color: var(--text-muted);
	}

	.tech-tag.matched {
		background: var(--primary-soft);
		border-color: var(--primary);
		color: var(--primary);
	}

	.loading {
		text-align: center;
		color: var(--text-muted);
		padding: 20px;
	}
</style>
