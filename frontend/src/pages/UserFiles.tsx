import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import apiClient from '../api/apiClient';
import { Trash2, ArrowLeft, Eye } from 'lucide-react';

export default function UserFiles() {
    const { userId } = useParams();
    const navigate = useNavigate();
    const [files, setFiles] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [deletingName, setDeletingName] = useState<string | null>(null);

    const fetchFiles = () => {
        apiClient.get(`/admin/users/${userId}/files`)
            .then(res => {
                setFiles(res.data.files);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching files:', err);
                setLoading(false);
            });
    };

    useEffect(() => {
        if (userId) {
            fetchFiles();
        }
    }, [userId]);

    const handleDelete = async (fileName: string) => {
        if (!window.confirm(`Are you sure you want to delete file "${fileName}"? This will delete all its chunks and cannot be undone.`)) {
            return;
        }

        setDeletingName(fileName);
        try {
            await apiClient.delete(`/admin/users/${userId}/files`, {
                params: { file_name: fileName }
            });
            setFiles(prev => prev.filter(f => f.file_name !== fileName));
        } catch (error: any) {
            console.error('Error deleting file:', error);
            alert('Failed to delete file');
        } finally {
            setDeletingName(null);
        }
    };

    if (loading) return <div className="p-4 sm:p-8 dark:text-gray-200">Loading...</div>;

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
                        <h1 className="text-lg sm:text-2xl font-bold dark:text-white">Files</h1>
                        <p className="text-xs sm:text-sm text-gray-500 dark:text-gray-400 break-all">User: {userId}</p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <Link
                        to={`/users/${userId}/graph`}
                        className="flex items-center gap-2 px-3 py-2 sm:px-4 sm:py-2 bg-blue-600 dark:bg-blue-500 text-white text-sm rounded hover:bg-blue-700 dark:hover:bg-blue-600 whitespace-nowrap"
                    >
                        <Eye size={16} />
                        <span className="hidden sm:inline">View Graph</span>
                        <span className="sm:hidden">Graph</span>
                    </Link>
                </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded shadow dark:shadow-gray-700 overflow-x-auto">
                <table className="min-w-full">
                    <thead className="bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">File Name</th>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Chunks</th>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Last Modified</th>
                            <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                        {files.map((file) => (
                            <tr key={file.file_name} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                                <td className="px-3 sm:px-6 py-4 text-xs sm:text-sm text-gray-900 dark:text-gray-200 break-all">
                                    {file.file_name}
                                </td>
                                <td className="px-3 sm:px-6 py-4 text-xs sm:text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                                    {file.chunk_count}
                                </td>
                                <td className="px-3 sm:px-6 py-4 text-xs sm:text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                                    {new Date(file.created_at).toLocaleString()}
                                </td>
                                <td className="px-3 sm:px-6 py-4 whitespace-nowrap">
                                    <button
                                        onClick={() => handleDelete(file.file_name)}
                                        disabled={deletingName === file.file_name}
                                        className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 disabled:opacity-50 p-1"
                                        title="Delete entire file"
                                    >
                                        <Trash2 size={16} className="sm:w-5 sm:h-5" />
                                    </button>
                                </td>
                            </tr>
                        ))}
                        {files.length === 0 && (
                            <tr>
                                <td colSpan={4} className="px-6 py-8 text-center text-gray-500 dark:text-gray-400">
                                    No files found for this user.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
