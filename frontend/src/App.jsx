import React, { useState } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import ConfigPanel from './components/ConfigPanel';
import TopicChat from './components/TopicChat';
import DataReview from './components/DataReview';
import DiscussionRoom from './components/DiscussionRoom';
import VisualizationPanel from './components/VisualizationPanel';
import PPTPreview from './components/PPTPreview';

function App() {
    const [isConfigured, setIsConfigured] = useState(false);
    const [currentStep, setCurrentStep] = useState('config'); // config, topic, data, retrieval, discussion, visualization, ppt
    const [projectData, setProjectData] = useState([]);

    const handleConfigComplete = () => {
        setIsConfigured(true);
        setCurrentStep('topic');
    };

    const handleTopicSelected = (topic) => {
        // TODO: Handle topic selection
        console.log("Selected topic:", topic);
        setCurrentStep('data');
    };

    const handleDataConfirmed = (data) => {
        console.log("Confirmed data:", data);
        setProjectData(data);
        // Move to next step
        setCurrentStep('discussion'); // Skip retrieval UI for now as it's backend only mostly
    };

    const handleDiscussionFinished = () => {
        setCurrentStep('visualization');
    };

    const handleVisualizationFinished = () => {
        setCurrentStep('ppt');
    };

    return (
        <ConfigProvider locale={zhCN}>
            <div className="min-h-screen bg-gray-100">
                {!isConfigured && currentStep === 'config' && (
                    <ConfigPanel onConfigComplete={handleConfigComplete} />
                )}

                {isConfigured && currentStep === 'topic' && (
                    <TopicChat onTopicSelected={handleTopicSelected} />
                )}

                {isConfigured && currentStep === 'data' && (
                    <DataReview onDataConfirmed={handleDataConfirmed} />
                )}

                {isConfigured && currentStep === 'discussion' && (
                    <DiscussionRoom onDiscussionFinished={handleDiscussionFinished} />
                )}

                {isConfigured && currentStep === 'visualization' && (
                    <VisualizationPanel data={projectData} onFinished={handleVisualizationFinished} />
                )}

                {isConfigured && currentStep === 'ppt' && (
                    <PPTPreview projectData={projectData} />
                )}
            </div>
        </ConfigProvider>
    );
}

export default App;
