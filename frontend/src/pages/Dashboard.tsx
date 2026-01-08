import { useEffect, useState } from 'react';
import apiClient from '../api/apiClient';
import { Link } from 'react-router-dom';
import { Trash2, Download, Upload } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';

export default function Dashboard() {
    const [stats, setStats] = useState<any>(null);
    const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
    const [backupUserId, setBackupUserId] = useState<string | null>(null);
    const [showRestoreDialog, setShowRestoreDialog] = useState(false);
    const [restoreFile, setRestoreFile] = useState<File | null>(null);
    const [restoreReplace, setRestoreReplace] = useState(false);
    const [restoring, setRestoring] = useState(false);
    // @ts-ignore - used in conditional JSX blocks
    const [restoreUserId, setRestoreUserId] = useState('');
    const [restoreUserExists, setRestoreUserExists] = useState(false);
    const [restoreNewUserId, setRestoreNewUserId] = useState('');

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
            `• All episodes (memories)\n• All entities (nodes)\n` +
            `• All relationships (edges)\n\nThis action cannot be undone!`
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

    const handleBackup = async (userId: string) => {
        setBackupUserId(userId);

        try {
            const response = await apiClient.get(`/admin/users/${userId}/backup`, {
                responseType: 'blob'
            });

            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `${userId}.tar.gz`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (error: any) {
            console.error('Error creating backup:', error);
            alert(`Failed to create backup for "${userId}": ${error.response?.data?.detail || error.message}`);
        } finally {
            setBackupUserId(null);
        }
    };

    const handleRestore = async () => {
        if (!restoreFile) {
            alert('Please select a backup file');
            return;
        }

        if (restoreUserExists && !restoreNewUserId.trim()) {
            alert('User already exists. Please enter a new user ID to restore with a different name.');
            return;
        }

        setRestoring(true);

        try {
            const formData = new FormData();
            formData.append('file', restoreFile);

            const params = new URLSearchParams();
            // Always use MERGE mode (replace=false) for safety
            params.append('replace', 'false');
            if (restoreUserExists && restoreNewUserId.trim()) {
                params.append('new_user_id', restoreNewUserId.trim());
            }

            const response = await apiClient.post(
                `/admin/users/restore?${params.toString()}`,
                formData,
                {
                    headers: {
                        'Content-Type': 'multipart/form-data'
                    }
                }
            );

            const result = response.data;
            alert(
                `Restore successful!\n\n` +
                `User: ${result.user_id}\n` +
                `Episodes: ${result.episodes_created} created\n` +
                `Entities: ${result.entities_created} created\n` +
                `Edges: ${result.edges_created} created\n` +
                (result.conflicts_skipped > 0 ? `\nSkipped ${result.conflicts_skipped} existing items (MERGE mode)` : '')
            );

            setShowRestoreDialog(false);
            setRestoreFile(null);
            setRestoreReplace(false);
            setRestoreUserId('');
            setRestoreUserExists(false);
            setRestoreNewUserId('');
            fetchUsers();
        } catch (error: any) {
            console.error('Error restoring backup:', error);
            alert(`Failed to restore backup: ${error.response?.data?.detail || error.message}`);
        } finally {
            setRestoring(false);
        }
    };

    return (
        <div className="p-4 sm:p-6 lg:p-8 pb-20">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                <h1 className="text-xl sm:text-2xl font-bold dark:text-white">Dashboard</h1>
                <div className="flex gap-3 items-center">
                    <button
                        onClick={() => setShowRestoreDialog(true)}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded inline-flex items-center gap-2 text-sm"
                        title="Restore user from backup"
                    >
                        <Upload size={16} />
                        Restore Backup
                    </button>
                    <ThemeToggle />
                </div>
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
                                        <button
                                            onClick={() => handleBackup(user.user_id)}
                                            disabled={backupUserId === user.user_id}
                                            className="text-green-600 hover:text-green-900 dark:text-green-400 dark:hover:text-green-300 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1 text-sm"
                                            title="Download backup"
                                        >
                                            <Download size={14} />
                                            {backupUserId === user.user_id ? 'Creating...' : 'Backup'}
                                        </button>
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
                                            {deletingUserId === user.user_id ? 'Del...' : 'Delete'}
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Restore Dialog */}
            {showRestoreDialog && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full p-6">
                        <h2 className="text-xl font-bold mb-4 dark:text-white">Restore User Backup</h2>

                        <div className="mb-4">
                            <label className="block text-sm font-medium mb-2 dark:text-gray-300">
                                Select Backup File (.tar.gz)
                            </label>
                            <input
                                type="file"
                                accept=".tar.gz,.tgz"
                                onChange={(e) => {
                                    const file = e.target.files?.[0] || null;
                                    setRestoreFile(file);
                                    if (file) {
                                        const userId = file.name.replace(/\.tar\.gz$/, '').replace(/\.tgz$/, '');
                                        setRestoreUserId(userId);
                                        const userExists = stats?.users?.some((u: any) => u.user_id === userId);
                                        setRestoreUserExists(userExists);
                                    }
                                }}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded dark:bg-gray-700 dark:text-white"
                            />
                        </div>

                        {restoreFile && restoreUserId && (
                            <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded">
                                <p className="text-sm dark:text-gray-300">
                                    <strong>User ID from backup:</strong> {restoreUserId}
                                </p>
                            </div>
                        )}

                        {restoreUserExists && restoreFile && (
                            <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded border border-yellow-300 dark:border-yellow-700">
                                <p className="text-sm text-yellow-800 dark:text-yellow-300 mb-3">
                                    ⚠️ User "{restoreUserId}" already exists. Choose action:
                                </p>

                                <div className="space-y-2">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="radio"
                                            name="restoreAction"
                                            checked={restoreReplace}
                                            onChange={() => setRestoreReplace(true)}
                                            className="w-4 h-4"
                                        />
                                        <span className="text-sm dark:text-gray-300">
                                            Replace existing data
                                        </span>
                                    </label>

                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="radio"
                                            name="restoreAction"
                                            checked={!restoreReplace}
                                            onChange={() => setRestoreReplace(false)}
                                            className="w-4 h-4"
                                        />
                                        <span className="text-sm dark:text-gray-300">
                                            Restore with new name
                                        </span>
                                    </label>
                                </div>

                                {!restoreReplace && (
                                    <div className="mt-3">
                                        <label className="block text-sm font-medium mb-1 dark:text-gray-300">
                                            New User ID:
                                        </label>
                                        <input
                                            type="text"
                                            value={restoreNewUserId}
                                            onChange={(e) => setRestoreNewUserId(e.target.value)}
                                            placeholder={`${restoreUserId}_v2`}
                                            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded dark:bg-gray-700 dark:text-white text-sm"
                                        />
                                    </div>
                                )}
                            </div>
                        )}

                        <div className="flex gap-3 justify-end">
                            <button
                                onClick={() => {
                                    setShowRestoreDialog(false);
                                    setRestoreFile(null);
                                    setRestoreReplace(false);
                                    setRestoreUserId('');
                                    setRestoreUserExists(false);
                                    setRestoreNewUserId('');
                                }}
                                disabled={restoring}
                                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleRestore}
                                disabled={!restoreFile || restoring || (restoreUserExists && !restoreReplace && !restoreNewUserId)}
                                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {restoring ? 'Restoring...' : 'Restore'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
