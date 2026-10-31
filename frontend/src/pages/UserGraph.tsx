import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GraphViewer3D, { GraphEdge, GraphNode } from '../components/GraphViewer3D';

const LIMIT_OPTIONS = [100, 300, 1000, 2000];
const DEFAULT_LIMIT = 300;
const COMMUNITY_COLOR = '#a855f7';

type ViewMode = 'entities' | 'communities';

interface GraphResponse {
    nodes: { data: GraphNode & { summary?: string; created_at?: string } }[];
    edges: { data: GraphEdge }[];
    total_nodes: number;
    total_edges: number;
    truncated: boolean;
    limit: number;
}

interface Community {
    uuid: string;
    name: string;
    summary: string;
    members: number;
}

interface CommunityBuildStatus {
    status: 'idle' | 'running' | 'done' | 'error';
    error?: string | null;
    communities?: number | null;
}

const buttonClass =
    'bg-white/10 hover:bg-white/20 text-white px-3 py-2 sm:px-4 sm:py-2 rounded backdrop-blur-sm transition-colors border border-white/20 flex items-center gap-2 text-sm sm:text-base disabled:opacity-50';

export default function UserGraph() {
    const { userId } = useParams();
    const [searchParams, setSearchParams] = useSearchParams();
    const [graph, setGraph] = useState<GraphResponse | null>(null);
    const [communities, setCommunities] = useState<Community[] | null>(null);
    const [selectedCommunity, setSelectedCommunity] = useState<Community | null>(null);
    const [mode, setMode] = useState<ViewMode>('entities');
    const [buildStatus, setBuildStatus] = useState<CommunityBuildStatus>({ status: 'idle' });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [limit, setLimit] = useState<number>(() => {
        const fromQuery = Number(searchParams.get('limit'));
        if (LIMIT_OPTIONS.includes(fromQuery)) return fromQuery;
        const stored = Number(localStorage.getItem('graphLimit'));
        return LIMIT_OPTIONS.includes(stored) ? stored : DEFAULT_LIMIT;
    });
    const abortRef = useRef<AbortController | null>(null);

    const startRequest = () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);
        setError(null);
        return controller;
    };

    const handleError = (err: any) => {
        if (err?.code === 'ERR_CANCELED') return; // aborted request, ignore
        const detail = err?.response?.data?.detail || err?.message || 'Неизвестная ошибка';
        setError(`Ошибка загрузки графа: ${detail}`);
        setLoading(false);
    };

    const fetchGraph = useCallback((lim: number, community: Community | null) => {
        const controller = startRequest();
        const url = community
            ? `/admin/users/${userId}/communities/${community.uuid}/members`
            : `/admin/users/${userId}/graph`;
        apiClient
            .get(url, { params: { limit: lim }, signal: controller.signal })
            .then(res => {
                if (res.data && Array.isArray(res.data.nodes) && Array.isArray(res.data.edges)) {
                    setGraph(res.data);
                } else {
                    setError('Не удалось прочитать ответ сервера');
                }
                setLoading(false);
            })
            .catch(handleError);
    }, [userId]);

    const fetchCommunities = useCallback(() => {
        const controller = startRequest();
        apiClient
            .get(`/admin/users/${userId}/communities`, { signal: controller.signal })
            .then(res => {
                setCommunities(res.data?.communities || []);
                setLoading(false);
            })
            .catch(handleError);
    }, [userId]);

    const reload = useCallback(() => {
        if (mode === 'communities' && !selectedCommunity) fetchCommunities();
        else fetchGraph(limit, selectedCommunity);
    }, [mode, selectedCommunity, limit, fetchGraph, fetchCommunities]);

    useEffect(() => {
        reload();
        return () => abortRef.current?.abort();
    }, [reload]);

    // Poll community build status while a build is running
    useEffect(() => {
        if (buildStatus.status !== 'running') return;
        const timer = window.setInterval(() => {
            apiClient
                .get(`/admin/users/${userId}/communities/status`)
                .then(res => {
                    setBuildStatus(res.data);
                    if (res.data?.status === 'done' && mode === 'communities') fetchCommunities();
                })
                .catch(() => undefined);
        }, 5000);
        return () => window.clearInterval(timer);
    }, [buildStatus.status, userId, mode, fetchCommunities]);

    useEffect(() => {
        apiClient
            .get(`/admin/users/${userId}/communities/status`)
            .then(res => setBuildStatus(res.data))
            .catch(() => undefined);
    }, [userId]);

    const handleLimitChange = (lim: number) => {
        setLimit(lim);
        localStorage.setItem('graphLimit', String(lim));
        setSearchParams(lim === DEFAULT_LIMIT ? {} : { limit: String(lim) }, { replace: true });
    };

    const handleModeChange = (next: ViewMode) => {
        setSelectedCommunity(null);
        setMode(next);
    };

    const buildCommunities = () => {
        apiClient
            .post(`/admin/users/${userId}/communities/build`)
            .then(() => setBuildStatus({ status: 'running' }))
            .catch(err => setBuildStatus({ status: 'error', error: err?.response?.data?.detail || err?.message }));
    };

    const showCommunityOverview = mode === 'communities' && !selectedCommunity;

    const nodes = useMemo<GraphNode[]>(() => {
        if (showCommunityOverview) {
            return (communities || []).map(c => ({
                id: c.uuid,
                label: `${c.name} (${c.members})`,
                degree: c.members,
                color: COMMUNITY_COLOR,
            }));
        }
        return (graph?.nodes || []).map(n => ({ ...n.data }));
    }, [showCommunityOverview, communities, graph]);

    const edges = useMemo<GraphEdge[]>(
        () => (showCommunityOverview ? [] : (graph?.edges || []).map(e => ({ ...e.data }))),
        [showCommunityOverview, graph]
    );

    const handleNodeClick = useCallback((nodeId: string) => {
        if (!showCommunityOverview) return;
        const community = (communities || []).find(c => c.uuid === nodeId);
        if (community) setSelectedCommunity(community);
    }, [showCommunityOverview, communities]);

    const toolbar = (
        <div className="absolute top-4 left-4 z-10 flex flex-wrap gap-2 max-w-[calc(100vw-2rem)]">
            <button onClick={() => window.history.back()} className={buttonClass}>
                ← <span className="hidden sm:inline">Back</span>
            </button>
            <button onClick={reload} className={buttonClass} title="Refresh graph">
                🔄 <span className="hidden sm:inline">Refresh</span>
            </button>
            <select
                value={mode}
                onChange={e => handleModeChange(e.target.value as ViewMode)}
                className={`${buttonClass} [&>option]:bg-gray-800 [&>option]:text-white`}
                title="Режим просмотра"
            >
                <option value="entities">Сущности</option>
                <option value="communities">Сообщества</option>
            </select>
            {!showCommunityOverview && (
                <select
                    value={limit}
                    onChange={e => handleLimitChange(Number(e.target.value))}
                    className={`${buttonClass} [&>option]:bg-gray-800 [&>option]:text-white`}
                    title="Лимит узлов"
                >
                    {LIMIT_OPTIONS.map(opt => (
                        <option key={opt} value={opt}>{opt} узлов</option>
                    ))}
                </select>
            )}
            {mode === 'communities' && selectedCommunity && (
                <button onClick={() => setSelectedCommunity(null)} className={buttonClass}>
                    ↩ Все сообщества
                </button>
            )}
            {mode === 'communities' && (
                <button
                    onClick={buildCommunities}
                    disabled={buildStatus.status === 'running'}
                    className={buttonClass}
                    title="Перестроить сообщества (кластеризация + LLM-сводки, может занять время)"
                >
                    {buildStatus.status === 'running' ? '⏳ Строим сообщества…' : '🧩 Построить сообщества'}
                </button>
            )}
        </div>
    );

    if (loading) return <div className="p-8 text-white bg-gray-900 h-screen flex items-center justify-center">Loading graph...</div>;

    if (error) {
        return (
            <div className="w-screen h-screen bg-gray-900 flex items-center justify-center">
                <div className="text-center max-w-md px-6">
                    <h2 className="text-2xl font-bold text-white mb-4">Ошибка загрузки графа</h2>
                    <p className="text-red-400 mb-6 break-words">{error}</p>
                    <div className="flex justify-center gap-3">
                        <button onClick={() => window.history.back()} className={buttonClass}>← Назад</button>
                        <button onClick={reload} className={buttonClass}>🔄 Повторить</button>
                    </div>
                </div>
            </div>
        );
    }

    let banner: string | null = null;
    if (showCommunityOverview) {
        banner = communities && communities.length > 0
            ? `Сообществ: ${communities.length}. Нажмите на сообщество, чтобы открыть его участников`
            : null;
    } else if (graph?.truncated) {
        banner = `Показано ${graph.nodes.length} из ${graph.total_nodes} узлов (${graph.edges.length} связей)`;
    }
    if (selectedCommunity) banner = `${selectedCommunity.name}: ${banner || `${nodes.length} узлов`}`;
    if (buildStatus.status === 'error') banner = `Ошибка построения сообществ: ${buildStatus.error || 'unknown'}`;

    const empty = nodes.length === 0;

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-gray-900">
            {toolbar}
            <div className="absolute top-4 right-4 z-10 pointer-events-none max-w-[200px] sm:max-w-none">
                <h1 className="text-sm sm:text-xl font-bold text-white/80 backdrop-blur-sm px-3 py-2 sm:px-4 sm:py-2 rounded bg-black/20 break-all">
                    Graph: {userId}
                </h1>
            </div>
            {banner && (
                <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-white/10 backdrop-blur-sm border border-white/20 rounded px-3 py-1.5 text-xs sm:text-sm text-white/90 max-w-[90vw] text-center">
                    {banner}
                </div>
            )}
            {empty ? (
                <div className="w-full h-full flex items-center justify-center">
                    <div className="text-center px-6">
                        <h2 className="text-2xl font-bold text-white mb-4">
                            {showCommunityOverview ? 'Сообщества ещё не построены' : 'No Graph Data'}
                        </h2>
                        <p className="text-gray-400">
                            {showCommunityOverview
                                ? 'Нажмите «Построить сообщества», чтобы сгруппировать сущности в тематические кластеры.'
                                : 'This user has no entities or relationships yet.'}
                        </p>
                    </div>
                </div>
            ) : (
                <GraphViewer3D nodes={nodes} edges={edges} onNodeClick={handleNodeClick} />
            )}
        </div>
    );
}
