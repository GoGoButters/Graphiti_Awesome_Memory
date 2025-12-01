import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext';
import GitHubButton from './components/GitHubButton';
import Dashboard from './pages/Dashboard';
import UserGraph from './pages/UserGraph';
import UserEpisodes from './pages/UserEpisodes';
import Login from './pages/Login';

const PrivateRoute = ({ children }: { children: JSX.Element }) => {
    const token = localStorage.getItem('token');
    return token ? children : <Navigate to="/login" />;
};

const Layout = ({ children }: { children: React.ReactNode }) => {
    const location = useLocation();
    const isLoginPage = location.pathname === '/login';

    return (
        <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">
            {!isLoginPage && <GitHubButton />}
            {children}
        </div>
    );
};

function App() {
    return (
        <ThemeProvider>
            <Router>
                <Layout>
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
                </Layout>
            </Router>
        </ThemeProvider>
    );
}

export default App;

