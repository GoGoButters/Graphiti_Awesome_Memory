import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import apiClient from '../api/apiClient';
import { Trash2, ArrowLeft, Eye } from 'lucide-react';

export default function UserEpisodes() {
    const { userId } = useParams();
    const navigate = useNavigate();
    const [episodes, setEpisodes] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [deletingId, setDeletingId] = useState<string | null>(null);

    const fetchEpisodes = () => {
        apiClient.get(`/admin/users/${userId}/episodes`)
            .then(res => {
                setEpisodes(res.data.episodes);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching episodes:', err);
                setLoading(false);
            });
    };

    useEffect(() => {
        if (userId) {
            fetchEpisodes();
        }
    }, [userId]);

    const handleDelete = async (uuid: string) => {
        if (!window.confirm('Are you sure you want to delete this episode? This action cannot be undone.')) {
            return;
        }

        setDeletingId(uuid);
        try {
            await apiClient.delete(`/admin/episodes/${uuid}`);
            setEpisodes(prev => prev.filter(e => e.uuid !== uuid));
        } catch (error: any) {
            console.error('Error deleting episode:', error);
            alert('Failed to delete episode');
        } finally {
            setDeletingId(null);
        }
    };

    if (loading) return <div className="p-8 dark:text-gray-200">Loading...</div>;

    return (
        <div className="p-8">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => navigate('/')}
                        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-full dark:text-gray-200"
                    >
                        <ArrowLeft size={24} />
                    </button>
                    <div>
                        <h1 className="text-2xl font-bold dark:text-white">Episodes for {userId}</h1>
                        <p className="text-gray-500 dark:text-gray-400">{episodes.length} episodes found</p>
                    </div>
                </div>
                <Link
                    to={`/users/${userId}/graph`}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600"
                >
                    <Eye size={18} />
                    View Graph
                </Link>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded shadow dark:shadow-gray-700 overflow-hidden">
                <table className="min-w-full">
                    <thead className="bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Created At</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Source</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Content Preview</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                        {episodes.map((episode) => (
                            <tr key={episode.uuid} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                    {new Date(episode.created_at).toLocaleString()}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                    {episode.source}
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400" title={episode.content}>
                                    <div className="max-w-md truncate">
                                        {episode.content}
                                    </div>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                    <button
                                        onClick={() => handleDelete(episode.uuid)}
                                        disabled={deletingId === episode.uuid}
                                        className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 disabled:opacity-50"
                                    >
                                        <Trash2 size={18} />
                                    </button>
                                </td>
                            </tr>
                        ))}
                        {episodes.length === 0 && (
                            <tr>
                                <td colSpan={4} className="px-6 py-8 text-center text-gray-500 dark:text-gray-400">
                                    No episodes found for this user.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
