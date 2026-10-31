import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Eye } from 'lucide-react';
import apiClient from '../api/apiClient';
import CommunityBuildControl from '../components/CommunityBuildControl';

interface Community {
    uuid: string;
    name: string;
    summary: string;
    members: number;
    created_at?: string | null;
}

export default function UserCommunities() {
    const { userId } = useParams();
    const navigate = useNavigate();
    const [communities, setCommunities] = useState<Community[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expanded, setExpanded] = useState<string | null>(null);

    const fetchCommunities = useCallback(() => {
        setLoading(true);
        setError(null);
        apiClient
            .get(`/admin/users/${userId}/communities`)
            .then(res => setCommunities(res.data?.communities || []))
            .catch(err => setError(err?.response?.data?.detail || err?.message || 'Ошибка загрузки'))
            .finally(() => setLoading(false));
    }, [userId]);

    useEffect(() => {
        if (userId) fetchCommunities();
    }, [userId, fetchCommunities]);

    if (!userId) return null;

    return (
        <div className="p-4 sm:p-6 lg:p-8 pb-20">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
                <div className="flex items-center gap-3 sm:gap-4">
                    <button
                        onClick={() => navigate('/')}
                        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full dark:text-gray-200"
                    >
                        <ArrowLeft size={20} className="sm:w-6 sm:h-6" />
                    </button>
                    <div>
                        <h1 className="text-lg sm:text-2xl font-bold dark:text-white">Сообщества</h1>
                        <p className="text-xs sm:text-sm text-gray-500 dark:text-gray-400 break-all">User: {userId}</p>
                    </div>
                </div>
                <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    <CommunityBuildControl userId={userId} onBuilt={fetchCommunities} />
                    <Link
                        to={`/users/${userId}/graph?mode=communities`}
                        className="flex items-center gap-2 px-3 py-2 sm:px-4 bg-blue-600 dark:bg-blue-500 text-white text-sm rounded hover:bg-blue-700 dark:hover:bg-blue-600 whitespace-nowrap"
                    >
                        <Eye size={16} />
                        Граф сообществ
                    </Link>
                </div>
            </div>

            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4 max-w-3xl">
                Сообщества — тематические кластеры сущностей графа со сводкой по каждому. Они дают общий обзор памяти
                пользователя и используются в профиле <code>/memory/users/{'{id}'}/profile</code>. После добавления
                новых записей их стоит перестроить.
            </p>

            {loading && <div className="dark:text-gray-200">Loading...</div>}
            {error && <div className="text-red-600 dark:text-red-400">{error}</div>}

            {!loading && !error && communities.length === 0 && (
                <div className="bg-white dark:bg-gray-800 rounded shadow dark:shadow-gray-700 p-8 text-center text-gray-500 dark:text-gray-400">
                    Сообщества ещё не построены. Нажмите «Построить сообщества».
                </div>
            )}

            {!loading && !error && communities.length > 0 && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {communities.map(c => {
                        const isOpen = expanded === c.uuid;
                        return (
                            <div key={c.uuid} className="bg-white dark:bg-gray-800 rounded shadow dark:shadow-gray-700 p-4">
                                <div className="flex items-start justify-between gap-3 mb-2">
                                    <h2 className="font-semibold dark:text-white break-words">{c.name || 'Без названия'}</h2>
                                    <span className="shrink-0 text-xs px-2 py-1 rounded bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200">
                                        {c.members} сущн.
                                    </span>
                                </div>
                                <p className={`text-sm text-gray-600 dark:text-gray-300 whitespace-pre-line ${isOpen ? '' : 'line-clamp-4'}`}>
                                    {c.summary || 'Нет сводки'}
                                </p>
                                <div className="flex gap-4 mt-3 text-sm">
                                    {c.summary && c.summary.length > 300 && (
                                        <button
                                            onClick={() => setExpanded(isOpen ? null : c.uuid)}
                                            className="text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
                                        >
                                            {isOpen ? 'Свернуть' : 'Показать полностью'}
                                        </button>
                                    )}
                                    <Link
                                        to={`/users/${userId}/graph?mode=communities&community=${c.uuid}`}
                                        className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                                    >
                                        Открыть граф участников →
                                    </Link>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
