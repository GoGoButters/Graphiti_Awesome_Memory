import { useEffect, useState } from 'react';
import apiClient from '../api/apiClient';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';

export default function Dashboard() {
    const [stats, setStats] = useState<any>(null);
    const [deletingUserId, setDeletingUserId] = useState<string | null>(null);

    const fetchUsers = () => {
        apiClient.get('/admin/users').then(res => setStats(res.data));
    };

    useEffect(() => {
        fetchUsers();
    }, []);

    const handleDelete = async (userId: string) => {
        const confirmed = window.confirm(
            `Are you sure you want to delete user "${userId}"?\n\n` +
            `This will permanently remove:\n` +
            `• All episodes (memories)\n` +
            `• All entities (nodes)\n` +
            `• All relationships (edges)\n\n` +
            `This action cannot be undone!`
        );

        if (!confirmed) return;

        setDeletingUserId(userId);

        try {
            await apiClient.delete(`/admin/users/${userId}`);
            alert(`User "${userId}" has been deleted successfully`);
            setStats((prev: any) => ({
                ...prev,
                users: prev.users.filter((u: any) => u.user_id !== userId),
                total: prev.total - 1
            }));
            fetchUsers();
        } catch (error: any) {
            console.error('Error deleting user:', error);
            alert(`Failed to delete user "${userId}": ${error.response?.data?.detail || error.message}`);
        } finally {
            setDeletingUserId(null);
        }
    };

    return (
        <div className="p-4 sm:p-6 lg:p-8 pb-20">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                <h1 className="text-xl sm:text-2xl font-bold dark:text-white">Dashboard</h1>
                <ThemeToggle />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6 mb-6 sm:mb-8">
                <div className="bg-white dark:bg-gray-800 p-4 sm:p-6 rounded shadow dark:shadow-gray-700">
                    <h3 className="text-gray-500 dark:text-gray-400 text-sm">Total Users</h3>
                    <p className="text-2xl sm:text-3xl font-bold dark:text-white">{stats?.total || 0}</p>
                </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded shadow dark:shadow-gray-700 overflow-x-auto">
                <table className="min-w-full">
                    <thead className="bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">User ID</th>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Episodes</th>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                        {stats?.users?.map((user: any) => (
                            <tr key={user.user_id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                                <td className="px-3 sm:px-6 py-4 text-sm dark:text-gray-200 break-all">{user.user_id}</td>
                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap dark:text-gray-200">{user.episodes_count}</td>
                                <td className="px-3 sm:px-6 py-4">
                                    <div className="flex flex-col sm:flex-row gap-2 sm:gap-3">
                                        <Link
                                            to={`/users/${user.user_id}/episodes`}
                                            className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 text-sm whitespace-nowrap"
                                        >
                                            Episodes
                                        </Link>
                                        <Link
                                            to={`/users/${user.user_id}/files`}
                                            className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 text-sm whitespace-nowrap"
                                        >
                                            Files
                                        </Link>
                                        <Link
                                            to={`/users/${user.user_id}/graph`}
                                            className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 text-sm whitespace-nowrap"
                                        >
                                            Graph
                                        </Link>
                                        <button
                                            onClick={() => handleDelete(user.user_id)}
                                            disabled={deletingUserId === user.user_id}
                                            className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1 text-sm"
                                            title="Delete user"
                                        >
                                            <Trash2 size={14} />
                                            {deletingUserId === user.user_id ? 'Deleting...' : 'Delete'}
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
