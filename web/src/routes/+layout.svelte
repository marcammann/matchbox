<script>
	import '../app.css';
	import { page } from '$app/stores';
	let { children } = $props();
</script>

<nav>
	<div class="nav-content">
		<a href="/jobs" class="logo">Matchbox <span class="version">v0.1.0</span></a>
		<div class="nav-links">
			<a href="/jobs" class:active={$page.url.pathname === '/jobs'}>Jobs</a>
			<a href="/settings" class:active={$page.url.pathname === '/settings'}>Settings</a>
		</div>
	</div>
</nav>

<main>
	{@render children()}
</main>

<style>
	.version {
		font-size: 11px;
		font-weight: 400;
		color: var(--text-muted);
		opacity: 0.6;
		margin-left: 2px;
	}
</style>
