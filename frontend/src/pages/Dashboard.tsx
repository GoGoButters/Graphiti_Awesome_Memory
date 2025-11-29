import { useEffect, useState } from 'react';
import apiClient from '../api/apiClient';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';

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
        // Confirmation dialog
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

            // Show success message
            alert(`User "${userId}" has been deleted successfully`);

            // Optimistic update: remove from list immediately
            setStats((prev: any) => ({
                ...prev,
                users: prev.users.filter((u: any) => u.user_id !== userId),
                total: prev.total - 1
            }));

            // Refresh the list from server
            fetchUsers();
        } catch (error: any) {
            console.error('Error deleting user:', error);
            alert(`Failed to delete user "${userId}": ${error.response?.data?.detail || error.message}`);
        } finally {
            setDeletingUserId(null);
        }
    };

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="bg-white p-6 rounded shadow">
                    <h3 className="text-gray-500 text-sm">Total Users</h3>
                    <p className="text-3xl font-bold">{stats?.total || 0}</p>
                </div>
                {/* Add more tiles */}
            </div>

            <div className="bg-white rounded shadow overflow-hidden">
                <table className="min-w-full">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User ID</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Episodes</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {stats?.users?.map((user: any) => (
                            <tr key={user.user_id}>
                                <td className="px-6 py-4 whitespace-nowrap">{user.user_id}</td>
                                <td className="px-6 py-4 whitespace-nowrap">{user.episodes_count}</td>
                                <td className="px-6 py-4 whitespace-nowrap space-x-3">
                                    <Link
                                        to={`/users/${user.user_id}/episodes`}
                                        className="text-blue-600 hover:text-blue-900"
                                    >
                                        View Episodes
                                    </Link>
                                    <Link
                                        to={`/users/${user.user_id}/graph`}
                                        className="text-blue-600 hover:text-blue-900"
                                    >
                                        View Graph
                                    </Link>
                                    <button
                                        onClick={() => handleDelete(user.user_id)}
                                        disabled={deletingUserId === user.user_id}
                                        className="text-red-600 hover:text-red-900 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1"
                                        title="Delete user"
                                    >
                                        <Trash2 size={16} />
                                        {deletingUserId === user.user_id ? 'Deleting...' : 'Delete'}
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
