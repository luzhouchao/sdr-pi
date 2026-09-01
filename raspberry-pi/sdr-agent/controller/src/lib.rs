pub mod autonomy;
pub mod execution;
pub mod planner;
pub mod policy;
pub mod protocol;
pub mod recognizer;
pub mod runner;
pub mod sdr;
pub mod sweep;

use planner::{Planner, PlannerError};
use policy::{ControllerPolicy, PolicyError};
use protocol::{PlanRequest, ValidatedPlan};
use std::error::Error;
use std::fmt;

pub struct Controller<P> {
    planner: P,
    policy: ControllerPolicy,
}

impl<P: Planner> Controller<P> {
    pub fn new(planner: P) -> Self {
        Self {
            planner,
            policy: ControllerPolicy,
        }
    }

    pub fn decide(&mut self, request: &PlanRequest) -> Result<ValidatedPlan, ControllerError> {
        self.policy.validate_request(request)?;
        let response = self.planner.plan(request)?;
        Ok(self.policy.validate_response(request, response)?)
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
