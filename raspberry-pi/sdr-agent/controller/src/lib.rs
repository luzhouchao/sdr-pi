pub mod autonomy;
pub mod batch_recognition;
mod bounded_audit;
pub mod execution;
pub mod live_recognition;
pub mod planner;
pub mod policy;
pub mod protocol;
pub mod received_window;
pub mod recognition_execution;
pub mod recognition_input;
pub mod recognition_result;
pub mod recognizer;
pub mod recognizer_admission;
pub mod runner;
pub mod sdr;
pub mod streaming_rx;
pub mod supervised_recognition;
pub mod sweep;

use planner::{Planner, PlannerError};
use policy::{ControllerPolicy, PolicyError};
use protocol::{PlanRequest, ValidatedPlan};
use std::error::Error;
use std::fmt;

pub struct Controller<P> {
    planner: P,
    policy: ControllerPolicy,
    recognizer: Box<dyn recognizer_admission::RecognizerCapability>,
}

impl<P: Planner> Controller<P> {
    pub fn new(planner: P) -> Self {
        Self {
            planner,
            policy: ControllerPolicy,
            recognizer: Box::new(recognizer_admission::UnavailableRecognizer),
        }
    }

    pub fn with_recognizer(
        mut self,
        recognizer: impl recognizer_admission::RecognizerCapability + 'static,
    ) -> Self {
        self.recognizer = Box::new(recognizer);
        self
    }

    pub fn decide(&mut self, request: &PlanRequest) -> Result<ValidatedPlan, ControllerError> {
        let mut request = request.clone();
        recognizer_admission::refresh_recognizer(&mut request, self.recognizer.as_mut());
        self.policy.validate_request(&request)?;
        let response = self.planner.plan(&request)?;
        recognizer_admission::refresh_recognizer(&mut request, self.recognizer.as_mut());
        Ok(self.policy.validate_response(&request, response)?)
    }
}

#[derive(Debug)]
pub enum ControllerError {
    Planner(PlannerError),
    Policy(PolicyError),
}

impl fmt::Display for ControllerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Planner(error) => write!(formatter, "planner: {error}"),
            Self::Policy(error) => write!(formatter, "policy: {error}"),
        }
    }
}

impl Error for ControllerError {}

impl From<PlannerError> for ControllerError {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

impl From<PolicyError> for ControllerError {
    fn from(error: PolicyError) -> Self {
        Self::Policy(error)
    }
}
