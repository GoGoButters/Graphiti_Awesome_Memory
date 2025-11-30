import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext';
import Dashboard from './pages/Dashboard';
import UserGraph from './pages/UserGraph';
import UserEpisodes from './pages/UserEpisodes';
import Login from './pages/Login';

const PrivateRoute = ({ children }: { children: JSX.Element }) => {
    const token = localStorage.getItem('token');
    return token ? children : <Navigate to="/login" />;
};

function App() {
    return (
        <ThemeProvider>
            <Router>
                <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">
                    <Routes>
                        <Route path="/login" element={<Login />} />
                        <Route path="/" element={
                            <PrivateRoute>
                                <Dashboard />
                            </PrivateRoute>
                        } />
                        <Route path="/users/:userId/graph" element={
                            <PrivateRoute>
                                <UserGraph />
                            </PrivateRoute>
                        } />
                        <Route path="/users/:userId/episodes" element={
                            <PrivateRoute>
                                <UserEpisodes />
                            </PrivateRoute>
                        } />
                    </Routes>
                </div>
            </Router>
        </ThemeProvider>
    );
}

export default App;
